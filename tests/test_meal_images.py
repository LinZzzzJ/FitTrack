"""Whole-frame image transport and safe, actionable model-output validation."""

import base64
import hashlib
import io

import pytest
from PIL import Image, ImageDraw

from conftest import food
from fittrack import ai
from fittrack.ai import AIClient, AIError, meal_image_bytes


COLORS = [(220, 20, 20), (20, 180, 20), (20, 20, 220), (220, 200, 20)]


def camera_photo(path, size, orientation=1):
    width, height = size
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for color, (left, top) in zip(COLORS, [(0, 0), (3, 0), (0, 3), (3, 3)], strict=True):
        draw.rectangle(
            (
                width * left // 4,
                height * top // 4,
                width * (left + 1) // 4 - 1,
                height * (top + 1) // 4 - 1,
            ),
            fill=color,
        )
    exif = Image.Exif()
    exif[274] = orientation
    exif[315] = "private-camera-metadata"
    image.save(path, "JPEG", quality=95, subsampling=0, exif=exif)


@pytest.mark.parametrize(
    "size,orientation,expected_size,corners",
    [
        ((3072, 4096), 1, (3072, 4096), [0, 1, 2, 3]),
        ((3072, 4096), 6, (4096, 3072), [2, 0, 3, 1]),
        ((6000, 2000), 1, (4096, 1365), [0, 1, 2, 3]),
    ],
)
def test_vision_request_preserves_all_corners_and_does_not_touch_source(
    tmp_path, monkeypatch, size, orientation, expected_size, corners
):
    path = tmp_path / "camera.jpg"
    camera_photo(path, size, orientation)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    received = []

    def capture(self, config, model, messages, limit):
        received.append(messages[1]["content"][1]["image_url"])
        return {"items": [food(90)], "assumptions": []}, {}

    monkeypatch.setattr(AIClient, "call", capture)
    AIClient().meal({"vision_model": "offline"}, path, "每袋60克，吃了两袋")
    assert len(received) == 1 and received[0]["detail"] == "high"
    payload = base64.b64decode(received[0]["url"].split(",", 1)[1])
    with Image.open(io.BytesIO(payload)) as sent:
        assert sent.size == expected_size
        assert not sent.getexif()
        for index, (x, y) in enumerate([(0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9)]):
            color = sent.getpixel((int(sent.width * x), int(sent.height * y)))
            assert (
                max(
                    abs(actual - expected)
                    for actual, expected in zip(color, COLORS[corners[index]], strict=True)
                )
                < 15
            )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_inline_size_bound_resizes_without_cropping(tmp_path, monkeypatch):
    path = tmp_path / "large.png"
    image = Image.effect_noise((1200, 1600), 40).convert("RGB")
    image.save(path)
    monkeypatch.setattr(ai, "MEAL_IMAGE_MAX_BYTES", 16000)
    payload = meal_image_bytes(path)
    assert len(payload) <= 16000
    with Image.open(io.BytesIO(payload)) as result:
        assert result.width < 1200 and result.height < 1600
        assert abs(result.width / result.height - 0.75) < 0.01


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("kcal", "missing", "热量（kcal）缺失"),
        ("protein_g", None, "蛋白质（g）应为数字，不能留空"),
        ("kcal", "90 kcal", "热量（kcal）应为不带单位的数字"),
        ("fat_g", float("inf"), "脂肪（g）不是有效有限数值"),
        ("private-provider-field", "private-provider-content", "包含未约定字段"),
    ],
)
def test_invalid_meal_fields_are_explained_without_echoing_provider_data(
    tmp_path, monkeypatch, field, value, expected
):
    path = tmp_path / "photo.jpg"
    camera_photo(path, (120, 160))
    item = food(90) | {"name": "private-food-name"}
    if value == "missing":
        del item[field]
    else:
        item[field] = value
    monkeypatch.setattr(AIClient, "call", lambda *args: ({"items": [item]}, {}))
    with pytest.raises(AIError) as caught:
        AIClient().meal({"vision_model": "offline"}, path, "private-user-note")
    assert expected in str(caught.value)
    assert "private-" not in str(caught.value)


def test_empty_recognition_remains_failure_instead_of_zero_intake(tmp_path, monkeypatch):
    path = tmp_path / "photo.jpg"
    camera_photo(path, (120, 160))
    monkeypatch.setattr(AIClient, "call", lambda *args: ({"items": [], "assumptions": []}, {}))
    with pytest.raises(AIError, match="食物列表内容不足或为空"):
        AIClient().meal({"vision_model": "offline"}, path, "")
