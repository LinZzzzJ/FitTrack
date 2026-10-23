import io
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from fastapi.testclient import TestClient
from PIL import Image

from fittrack.app import create_app
from fittrack.config import Settings
from fittrack.store import Store


def pytest_configure(config):
    """Keep direct pytest runs inside the same explicit checks area as check.ps1."""
    checks = Path(__file__).resolve().parents[1] / "artifacts" / "checks"
    scratch = checks / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    for key in ("TMP", "TEMP", "TMPDIR", "SQLITE_TMPDIR"):
        os.environ[key] = str(scratch)
    tempfile.tempdir = str(scratch)
    if not config.option.basetemp:
        config.option.basetemp = str(checks / f"pytest-{uuid4().hex[:12]}")


class FakeAI:
    def meal_label(self, config, path, note):
        return {
            "name": "鸡胸肉丸",
            "basis_kind": "per_100g",
            "basis_grams": 100,
            "energy_value": 374,
            "energy_unit": "kJ",
            "protein_g": 13.2,
            "carbs_g": 6.4,
            "fat_g": 1.1,
            "assumptions": ["请人工确认标签与食用份量"],
        }, {"total_tokens": 10}

    def cardio_estimate(self, config, context):
        return {
            "effective_met": 6,
            "rationale": "结合运动类型和含休息总时长估算整段平均强度。",
            "assumptions": [context["input"]["description"] or "按填写的强度估算"],
        }, {"total_tokens": 10}

    def weekly_review(self, config, context):
        return {
            "summary": "本周坚持完整记录，按长期趋势稳步调整。",
            "diet_findings": ["核对每天的营养分配"],
            "training_findings": ["休息日也有价值"],
            "next_week_plan": ["延续记录并按恢复状态安排训练"],
            "limitations": ["热量消耗为估计"],
        }, {"total_tokens": 10}

    def goals(self, config, context):
        return {
            "calorie_target": 1800,
            "protein_target_g": 120,
            "carbs_target_g": 195,
            "fat_target_g": 60,
            "rationale": "以估计维持消耗为基础，温和调整摄入并支持训练。",
            "assumptions": ["使用已有身体资料，未记录的运动不额外推测。"],
        }, {"total_tokens": 10}

    def meal(self, config, path, note):
        return {
            "items": [
                {
                    "name": "鸡蛋蛋白",
                    "consumed_part": "只吃蛋白",
                    "estimated_edible_grams": 100,
                    "kcal": 52,
                    "protein_g": 11,
                    "carbs_g": 0.7,
                    "fat_g": 0.2,
                }
            ],
            "assumptions": [note],
            "total_kcal": 52,
        }, {"total_tokens": 10}

    def meal_description(self, config, description, note="", path=None):
        return {
            "items": [
                {
                    "name": "米饭和鸡胸肉",
                    "consumed_part": "按文字描述估算",
                    "estimated_edible_grams": 250,
                    "kcal": 390,
                    "protein_g": 38,
                    "carbs_g": 52,
                    "fat_g": 4,
                    "fiber_g": None,
                    "sugar_g": None,
                    "sodium_mg": None,
                }
            ],
            "assumptions": [description, note],
            "total_kcal": 390,
        }, {"total_tokens": 10}

    def feedback(self, config, context):
        return {
            "summary": "已记录摄入与估计消耗",
            "positives": ["坚持记录"],
            "adjustments": [],
            "next_day_advice": "继续补充完整记录",
        }, {"total_tokens": 10}


@pytest.fixture(autouse=True)
def no_paid_requests(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Automatic tests must not contact paid AI providers")

    monkeypatch.setattr(requests, "post", blocked)


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "data")
    yield result
    result.close()


@pytest.fixture
def app(store, tmp_path):
    env = tmp_path / ".env"
    env.write_text("FITTRACK_AI_API_KEY=test-only-placeholder\n", encoding="utf-8")
    return create_app(
        store,
        Settings(env),
        ai=FakeAI(),
        allowed_hosts=frozenset({"testserver", "127.0.0.1", "localhost"}),
    )


@pytest.fixture
def client(app):
    with TestClient(app) as result:
        yield result


def register(client, name="alice"):
    response = client.post(
        "/api/auth/register", json={"username": name, "password": "test-password-123"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def profile(day="2026-10-14"):
    return {
        "effective_date": day,
        "height_cm": 175,
        "initial_weight_kg": 75,
        "sex": "male",
        "resting_kcal": 1800,
        "activity_factor": 1.2,
        "calorie_target": 2000,
    }


def food(kcal=2000):
    return {
        "name": "测试餐",
        "consumed_part": "全部",
        "estimated_edible_grams": 100,
        "kcal": kcal,
        "protein_g": 10,
        "carbs_g": 20,
        "fat_g": 5,
    }


def meal(day="2026-10-14", kcal=2000):
    return {"date": day, "slot": "lunch", "items": [food(kcal)]}


def picture():
    output = io.BytesIO()
    Image.new("RGB", (80, 60), "orange").save(output, "PNG")
    return output.getvalue()
