import threading

import pytest
from fastapi.testclient import TestClient

from fittrack.ai import AIClient, AIError
from fittrack.models import GoalProfile

from conftest import FakeAI, profile, register
from test_core import wait_job


def goal_request(**updates):
    draft = GoalProfile.model_validate({**profile(), "target_weight_kg": 65}).model_dump(
        mode="json"
    )
    return {
        "kind": "goals",
        "date": "2026-10-14",
        "request_key": "goal-test-request",
        "goal_profile": draft,
        **updates,
    }


def test_generate_from_unsaved_profile_without_mutating_targets(client, app):
    calls = []

    class RecordingAI(FakeAI):
        def goals(self, config, context):
            calls.append(context)
            return super().goals(config, context)

    app.state.runner.ai = RecordingAI()
    register(client)
    request = goal_request()
    response = client.post("/api/jobs", json=request)
    assert response.status_code == 202
    job = wait_job(client, response.json()["id"])
    assert job["status"] == "done"
    assert job["result"]["goals"]["calorie_target"] == 1800
    assert not job["result"]["stale"]
    assert calls[0]["estimated_maintenance_kcal"] == 2160
    assert calls[0]["recorded_training_days_7d"] == 0
    assert "calorie_target" not in calls[0]["profile"]
    assert client.get("/api/me").json()["profile"] is None
    assert client.get("/api/days/2026-10-14").json()["feedback"] is None
    assert client.post("/api/jobs", json=request).json()["id"] == job["id"]
    assert len(calls) == 1
    # Adoption remains an explicit ordinary profile save.
    targets = {
        key: value
        for key, value in job["result"]["goals"].items()
        if key.endswith("_target") or key.endswith("_target_g")
    }
    assert (
        client.put("/api/profile", json={**request["goal_profile"], **targets}).status_code == 200
    )
    assert client.get("/api/me").json()["profile"]["protein_target_g"] == 120


def test_goal_input_validation_and_owner_isolation(client, app):
    register(client)
    request = goal_request()
    request["goal_profile"]["target_weight_kg"] = None
    assert client.post("/api/jobs", json=request).status_code == 422
    assert client.post("/api/jobs", json=goal_request(goal_profile=None)).status_code == 422
    assert client.post("/api/jobs", json=goal_request(kind="feedback")).status_code == 422
    job = wait_job(client, client.post("/api/jobs", json=goal_request()).json()["id"])
    with TestClient(app) as other:
        register(other, "other-goal-user")
        assert other.get(f"/api/jobs/{job['id']}").status_code == 404
        assert other.get("/api/days/2026-10-14").json()["jobs"] == []
    assert client.get("/api/me").json()["profile"] is None


def test_goal_basis_uses_recent_weight_and_seven_calendar_days(client, app):
    register(client)
    client.put("/api/profile", json=profile())
    client.put("/api/body", json={"date": "2026-10-13", "weight_kg": 74})
    client.put("/api/body", json={"date": "2026-10-15", "weight_kg": 80})
    client.post(
        "/api/workouts",
        json={
            "date": "2026-10-14",
            "title": "测试有氧",
            "kind": "cardio",
            "activity": "running",
            "duration_minutes": 60,
            "intensity": "moderate",
            "met": 6,
        },
    )
    job = wait_job(client, client.post("/api/jobs", json=goal_request()).json()["id"])
    basis = job["result"]["basis"]
    assert basis["current_weight_kg"] == 74
    assert basis["recorded_training_days_7d"] == 1
    assert basis["average_exercise_net_kcal_7d"] == 52.7
    assert basis["estimated_maintenance_kcal"] == 2212.7
    # Later changes invalidate completed suggestions, not the stored user targets.
    client.put("/api/body", json={"date": "2026-10-14", "weight_kg": 73, "resting_kcal": 1900})
    assert client.get(f"/api/jobs/{job['id']}").json()["result"]["stale"]
    assert client.get("/api/days/2026-10-14").json()["jobs"][0]["result"]["stale"]
    assert client.get("/api/me").json()["profile"]["calorie_target"] == 2000


def test_record_change_while_generating_goal_is_stale(client, app):
    started, release = threading.Event(), threading.Event()

    class WaitingAI(FakeAI):
        def goals(self, config, context):
            started.set()
            assert release.wait(timeout=5)
            return super().goals(config, context)

    app.state.runner.ai = WaitingAI()
    register(client)
    job = client.post("/api/jobs", json=goal_request()).json()
    try:
        assert started.wait(timeout=5)
        client.put("/api/body", json={"date": "2026-10-14", "weight_kg": 73})
    finally:
        release.set()
    assert wait_job(client, job["id"])["result"]["stale"]


@pytest.mark.parametrize(
    "invalid",
    [
        {"calorie_target": 800},
        {"carbs_target_g": 500},
        {"fat_target_g": float("nan")},
        {"protein_target_g": -1},
    ],
)
def test_ai_goal_validation_rejects_invalid_nutrition(invalid, monkeypatch):
    result, _ = FakeAI().goals({}, {})
    monkeypatch.setattr(AIClient, "call", lambda *a: ({**result, **invalid}, {}))
    with pytest.raises(AIError, match="格式或营养供能异常"):
        AIClient().goals({"coach_model": "test"}, {})


@pytest.mark.parametrize(
    "target,kcal,valid",
    [
        (65, 1800, True),
        (65, 1500, False),
        (65, 2300, False),
        (80, 2300, True),
        (80, 2600, False),
        (80, 1800, False),
        (75, 2160, True),
        (75, 1800, False),
    ],
)
def test_ai_goal_calories_follow_direction_and_moderate_bounds(target, kcal, valid, monkeypatch):
    result, _ = FakeAI().goals({}, {})
    result.update(calorie_target=kcal, carbs_target_g=(kcal - 120 * 4 - 60 * 9) / 4)
    monkeypatch.setattr(AIClient, "call", lambda *a: (result, {}))
    context = {
        "estimated_maintenance_kcal": 2160,
        "current_weight_kg": 75,
        "profile": {"target_weight_kg": target},
    }
    if valid:
        suggestion, _ = AIClient().goals({"coach_model": "test"}, context)
        assert suggestion["calorie_target"] == kcal
    else:
        with pytest.raises(AIError, match="温和调整范围"):
            AIClient().goals({"coach_model": "test"}, context)


def test_goal_failure_keeps_existing_targets(client, app):
    class FailingAI(FakeAI):
        def goals(self, config, context):
            raise AIError("模拟网络失败")

    app.state.runner.ai = FailingAI()
    register(client)
    client.put("/api/profile", json=profile())
    job = wait_job(client, client.post("/api/jobs", json=goal_request()).json()["id"])
    assert job["status"] == "failed"
    assert job["request"]["goal_profile"]["target_weight_kg"] == 65
    assert client.get("/api/me").json()["profile"]["calorie_target"] == 2000
