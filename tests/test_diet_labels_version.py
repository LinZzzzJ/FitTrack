import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import meal, picture, register
from fittrack import version
from fittrack.ai import AIClient
from test_coaching import finish


def label_snapshot(packs=1):
    return {
        "label": {
            "name": "鸡胸肉丸",
            "basis_kind": "per_100g",
            "basis_grams": 100,
            "energy_value": 374,
            "energy_unit": "kJ",
            "protein_g": 13.2,
            "carbs_g": 6.4,
            "fat_g": 1.1,
            "assumptions": [],
        },
        "portion": {"mode": "packs", "grams": None, "pack_grams": 60, "packs": packs},
    }


@pytest.mark.parametrize(
    "packs,kcal,protein", [(1, 53.63, 7.92), (2, 107.27, 15.84), (0.5, 26.82, 3.96)]
)
def test_label_kj_portions_preview_and_authoritative_save(client, packs, kcal, protein):
    register(client)
    snapshot = label_snapshot(packs)
    response = client.post("/api/nutrition-label/preview", json=snapshot)
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["kcal"] == kcal and item["protein_g"] == protein
    assert not client.get("/api/days/2026-10-14").json()["meals"]
    saved = client.post("/api/meals", json=meal(kcal=9999) | {"nutrition_label": snapshot})
    assert saved.status_code == 201, saved.text
    assert saved.json()["items"] == [item]
    assert client.get("/api/days/2026-10-14").json()["totals"]["kcal"] == kcal


def test_label_kcal_serving_and_grams(client):
    register(client)
    snapshot = label_snapshot()
    snapshot["label"].update(
        basis_kind="per_serving", basis_grams=50, energy_unit="kcal", energy_value=100
    )
    snapshot["portion"].update(mode="grams", grams=75, packs=99)
    assert client.post("/api/nutrition-label/preview", json=snapshot).json()["item"]["kcal"] == 150


@pytest.mark.parametrize(
    "change", ["missing", "unit", "negative", "zero_portion", "basis", "oversize"]
)
def test_invalid_label_blocks_confirmation(client, change):
    register(client)
    snapshot = label_snapshot()
    if change == "missing":
        snapshot["label"]["protein_g"] = None
    elif change == "unit":
        snapshot["label"]["energy_unit"] = None
    elif change == "negative":
        snapshot["label"]["energy_value"] = -1
    elif change == "zero_portion":
        snapshot["portion"]["packs"] = 0
    elif change == "basis":
        snapshot["label"]["basis_grams"] = 60
    else:
        snapshot["portion"].update(pack_grams=10000, packs=1000)
    assert client.post("/api/nutrition-label/preview", json=snapshot).status_code in {400, 422}
    assert client.post("/api/meals", json=meal() | {"nutrition_label": snapshot}).status_code in {
        400,
        422,
    }
    assert not client.get("/api/days/2026-10-14").json()["meals"]


def test_label_jobs_preserve_date_partial_readout_and_duplicate_protection(client, app):
    register(client)
    image = client.post(
        "/api/uploads", files={"file": ("label.png", picture(), "image/png")}
    ).json()
    job = finish(
        client,
        client.post(
            "/api/jobs",
            json={
                "kind": "meal",
                "meal_mode": "label",
                "date": "2026-10-14",
                "slot": "snack",
                "image_id": image["id"],
                "note": "每袋60克",
                "request_key": "label-job-test",
            },
        ),
    )
    assert job["status"] == "done", job
    assert job["result"]["label"]["energy_value"] == 374
    assert "items" not in job["result"]
    snapshot = label_snapshot()
    entry = meal() | {
        "image_id": image["id"],
        "source_job_id": job["id"],
        "nutrition_label": snapshot,
    }
    saved = client.post("/api/meals", json=entry).json()
    assert client.post("/api/meals", json=entry).json()["id"] == saved["id"]
    snapshot["portion"]["packs"] = 2
    assert client.put(f"/api/meals/{saved['id']}", json=entry).json()["items"][0]["kcal"] == 107.27
    other = TestClient(app)
    try:
        register(other, "bob")
        assert other.post("/api/meals", json=entry).status_code == 404
        assert other.get(f"/api/jobs/{job['id']}").status_code == 404
    finally:
        other.close()


def test_label_ai_missing_values_remain_null(tmp_path, monkeypatch):
    path = tmp_path / "label.png"
    path.write_bytes(picture())
    monkeypatch.setattr(
        AIClient,
        "call",
        lambda *args: ({"name": "partial", "energy_value": 374, "energy_unit": "kJ"}, {}),
    )
    result, _ = AIClient().meal_label({"vision_model": "offline"}, path, "")
    assert result["protein_g"] is None and result["basis_grams"] is None


def test_diet_history_cross_week_year_old_dates_and_ownership(client, app):
    register(client)
    for day in ["2026-10-14", "2026-10-15", "2026-10-21", "2026-10-22", "2026-12-31", "2027-01-01"]:
        assert client.post("/api/meals", json=meal(day, 100)).status_code == 201
    for start, end, expected in [
        ("2026-10-08", "2026-10-14", 1),
        ("2026-10-15", "2026-10-21", 2),
        ("2026-12-31", "2027-01-06", 2),
    ]:
        rows = client.get(f"/api/diet-history?start={start}&end={end}").json()["days"]
        assert len(rows) == 7 and sum(len(row["meals"]) for row in rows) == expected
    assert client.get("/api/diet-history?start=2026-10-15&end=2026-10-22").status_code == 400
    other = TestClient(app)
    try:
        register(other, "bob")
        assert all(
            not row["meals"]
            for row in other.get("/api/diet-history?start=2026-10-15&end=2026-10-21").json()["days"]
        )
    finally:
        other.close()


def test_version_is_public_and_mismatch_prevents_mutation(client, app, monkeypatch):
    info = client.get("/api/version")
    assert info.status_code == 200 and info.json()["api_revision"] == 5
    assert "nutrition_label" in info.json()["capabilities"]
    assert "meal_job_delete" in info.json()["capabilities"]
    assert "precise_meal_energy" in info.json()["capabilities"]
    assert not info.json()["restart_required"] and "D:" not in info.text
    register(client)
    assert (
        client.post("/api/meals", json=meal(), headers={"x-fittrack-api": "1"}).status_code == 409
    )
    monkeypatch.setattr(version, "source_fingerprint", lambda: "changed-on-disk")
    assert client.get("/api/version").json()["restart_required"]
    assert client.post("/api/meals", json=meal()).status_code == 409
    assert not client.get("/api/days/2026-10-14").json()["meals"]
    assert client.post("/api/auth/logout").status_code == 204


def test_restart_timeout_never_starts_or_kills_process(tmp_path, monkeypatch):
    from fittrack import cli

    folder = tmp_path / "runtime"
    folder.mkdir()
    (folder / "service.json").write_text(
        json.dumps({"url": "http://127.0.0.1:1", "instance": "owned-test"})
    )
    calls = []
    monkeypatch.setattr(cli, "existing", lambda *args, **kwargs: calls.append(kwargs) or True)
    with pytest.raises(ValueError, match="未强制终止"):
        cli.restart_existing(SimpleNamespace(root=tmp_path), timeout=0)
    assert calls == [{"stop": True, "open_browser": False}]
