import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import FakeAI, meal, profile, register
from fittrack import calculations
from fittrack.ai import AIClient, AIError


def finish(client, response):
    assert response.status_code == 202, response.text
    ident = response.json()["id"]
    for _ in range(300):
        value = client.get(f"/api/jobs/{ident}").json()
        if value["status"] not in {"queued", "running"}:
            return value
        time.sleep(0.01)
    raise AssertionError("AI task did not finish")


def cardio_request(day="2026-10-15", key="cardio-estimate-1"):
    return {
        "kind": "cardio_estimate",
        "date": day,
        "request_key": key,
        "cardio_input": {
            "kind": "cardio",
            "activity": "badminton",
            "duration_minutes": 60,
            "intensity": "moderate",
            "description": "中间休息20分钟，实际打球40分钟",
        },
    }


def workout_from(job):
    values = job["request"]["cardio_input"]
    return {
        "date": job["date"],
        "title": "羽毛球",
        "kind": "cardio",
        "activity": values["activity"],
        "duration_minutes": values["duration_minutes"],
        "intensity": values["intensity"],
        "note": values["description"],
        "met": job["result"]["estimate"]["effective_met"],
        "net_kcal_override": None,
        "ai_estimate_job_id": job["id"],
    }


def seed_week(store, uid):
    store.save_profile(uid, profile("2026-10-15"))
    for offset in range(7):
        day = (date(2026, 10, 15) + timedelta(days=offset)).isoformat()
        store.save_entry(uid, "meal", meal(day, kcal=2000))
        store.complete_day(uid, day)


def weekly_request(key="weekly-review-1", start="2026-10-15"):
    return {
        "kind": "weekly_review",
        "date": (date.fromisoformat(start) + timedelta(days=6)).isoformat(),
        "week_start": start,
        "request_key": key,
    }


def test_trend_cutoff_and_chunk_boundary(client):
    register(client)
    for day, value in [
        ("2026-10-14", 100),
        ("2026-10-15", 75),
        ("2026-10-17", 73),
        ("2027-10-14", 70),
        ("2027-10-16", 68),
    ]:
        assert client.put("/api/body", json={"date": day, "weight_kg": value}).status_code == 200
    data = client.get(
        "/api/trends?start=2026-10-15&end=2026-10-17&measurement_start=2026-10-15"
    ).json()["days"]
    assert data[0]["weight_average_7d"] == 75
    assert data[1]["body"] is None
    assert data[2]["weight_average_7d"] == 74
    assert (
        client.get("/api/trends?start=2026-10-15&end=2026-10-15").json()["days"][0][
            "weight_average_7d"
        ]
        == 87.5
    )
    assert (
        client.get(
            "/api/trends?start=2027-10-16&end=2027-10-16&measurement_start=2026-10-15"
        ).json()["days"][0]["weight_average_7d"]
        == 69
    )


def test_badminton_manual_and_ai_preview_adoption(client, store):
    uid = register(client)["id"]
    client.put("/api/profile", json=profile("2026-10-15"))
    activity = next(x for x in client.get("/api/me").json()["activities"] if x["id"] == "badminton")
    assert activity["mets"] == {"light": 5.5, "moderate": 7, "vigorous": 9}
    job = finish(client, client.post("/api/jobs", json=cardio_request()))
    assert job["status"] == "done", job
    assert job["result"]["estimate"]["gross_kcal"] == 450
    assert job["result"]["estimate"]["net_kcal"] == 375
    assert not store.entries(uid, "workout", "2026-10-15", "2026-10-15")
    saved = client.post("/api/workouts", json=workout_from(job))
    assert saved.status_code == 201, saved.text
    day = client.get("/api/days/2026-10-15").json()
    assert day["exercise_kcal"] == 375
    assert "AI" in day["workouts"][0]["energy"]["source"]
    manual = workout_from(job) | {"met": None, "ai_estimate_job_id": None, "intensity": "light"}
    assert client.post("/api/workouts", json=manual).status_code == 201
    assert client.get("/api/days/2026-10-15").json()["exercise_kcal"] == 375 + 337.5


@pytest.mark.parametrize(
    "change",
    [
        "description",
        "duration_minutes",
        "activity",
        "intensity",
        "date",
        "weight",
        "resting",
        "met",
        "override",
    ],
)
def test_cardio_source_rejects_changed_inputs(client, change):
    register(client)
    client.put("/api/profile", json=profile("2026-10-15"))
    job = finish(client, client.post("/api/jobs", json=cardio_request()))
    payload = workout_from(job)
    if change == "description":
        payload["note"] = "改为全程高强度"
    elif change == "duration_minutes":
        payload["duration_minutes"] = 90
    elif change == "activity":
        payload["activity"] = "running"
    elif change == "intensity":
        payload["intensity"] = "vigorous"
    elif change == "date":
        payload["date"] = "2026-10-16"
    elif change in {"weight", "resting"}:
        client.put(
            "/api/body",
            json={"date": "2026-10-15", "weight_kg": 80}
            if change == "weight"
            else {"date": "2026-10-15", "resting_kcal": 2000},
        )
        assert client.get(f"/api/jobs/{job['id']}").json()["result"]["stale"]
    elif change == "met":
        payload["met"] = 8
    else:
        payload["net_kcal_override"] = 500
    assert client.post("/api/workouts", json=payload).status_code == 400
    assert client.get("/api/days/2026-10-15").json()["exercise_kcal"] == 0


def test_cardio_rejects_strength_and_other_account(client, app):
    register(client)
    client.put("/api/profile", json=profile("2026-10-15"))
    bad = cardio_request()
    bad["cardio_input"]["kind"] = "strength"
    assert client.post("/api/jobs", json=bad).status_code == 422
    bad["cardio_input"]["kind"] = "cardio"
    bad["cardio_input"]["activity"] = "strength"
    assert client.post("/api/jobs", json=bad).status_code == 400
    job = finish(client, client.post("/api/jobs", json=cardio_request()))
    other = TestClient(app)
    try:
        register(other, "bob")
        other.put("/api/profile", json=profile("2026-10-15"))
        assert other.get(f"/api/jobs/{job['id']}").status_code == 404
        assert other.post("/api/workouts", json=workout_from(job)).status_code == 404
    finally:
        other.close()


def test_week_eligibility_clock_and_rest_days(client, store, monkeypatch):
    uid = register(client)["id"]
    seed_week(store, uid)
    monkeypatch.setattr(calculations, "today", lambda: "2026-10-21")
    status = client.get("/api/weekly-review").json()
    assert status["completed_days"] == 7 and not status["can_generate"]
    assert status["earliest_generation_date"] == "2026-10-22"
    assert client.post("/api/jobs", json=weekly_request()).status_code == 400
    monkeypatch.setattr(calculations, "today", lambda: "2026-10-22")
    status = client.get("/api/weekly-review").json()
    assert status["can_generate"] and status["statistics"]["rest_days"] == 7
    job = finish(client, client.post("/api/jobs", json=weekly_request()))
    assert job["status"] == "done", job
    assert job["result"]["statistics"]["intake_total_kcal"] == 14000
    assert job["result"]["statistics"]["weight_change_kg"] is None
    assert client.get("/api/weekly-review").json()["report"]["id"] == job["id"]
    assert client.post("/api/jobs", json=weekly_request()).json()["id"] == job["id"]
    assert client.get("/api/weekly-review?week_start=2026-10-16").status_code == 400
    assert (
        client.post(
            "/api/jobs", json=weekly_request("future-week-2", start="2026-10-22")
        ).status_code
        == 400
    )


@pytest.mark.parametrize("missing", ["meal", "completion"])
def test_week_missing_record_blocks_without_ai(client, store, app, monkeypatch, missing):
    uid = register(client)["id"]
    seed_week(store, uid)
    monkeypatch.setattr(calculations, "today", lambda: "2026-10-22")
    if missing == "meal":
        store.db.execute("DELETE FROM entries WHERE user_id=? AND date='2026-10-18'", (uid,))
    else:
        store.db.execute("DELETE FROM days WHERE user_id=? AND date='2026-10-18'", (uid,))

    class NeverAI:
        def weekly_review(self, *args):
            raise AssertionError("Ineligible records must never reach AI")

    app.state.runner.ai = NeverAI()
    status = client.get("/api/weekly-review").json()
    assert not status["can_generate"] and status["completed_days"] == 6
    assert status["missing_dates"][0]["date"] == "2026-10-18"
    assert client.post("/api/jobs", json=weekly_request()).status_code == 400
    assert not store.rows("SELECT * FROM jobs")


def test_week_stale_failure_preserves_report_and_isolation(client, store, app, monkeypatch):
    uid = register(client)["id"]
    seed_week(store, uid)
    monkeypatch.setattr(calculations, "today", lambda: "2026-10-22")
    first = finish(client, client.post("/api/jobs", json=weekly_request()))
    store.save_entry(uid, "meal", meal("2026-10-16", 100))
    assert client.get("/api/weekly-review").json()["report"]["result"]["stale"]

    class Failed(FakeAI):
        def weekly_review(self, *args):
            raise AIError("模拟服务不可用")

    app.state.runner.ai = Failed()
    failed = finish(client, client.post("/api/jobs", json=weekly_request("weekly-retry-1")))
    assert failed["status"] == "failed"
    assert client.get("/api/weekly-review").json()["report"]["id"] == first["id"]
    other = TestClient(app)
    try:
        register(other, "bob")
        assert not other.get("/api/weekly-review").json()["report"]
        assert other.get(f"/api/jobs/{first['id']}").status_code == 404
    finally:
        other.close()


def test_week_concurrent_generation_reuses_active_task(client, store, app, monkeypatch):
    uid = register(client)["id"]
    seed_week(store, uid)
    monkeypatch.setattr(calculations, "today", lambda: "2026-10-22")
    entered, release = threading.Event(), threading.Event()

    class Slow(FakeAI):
        def weekly_review(self, config, context):
            entered.set()
            release.wait(5)
            return super().weekly_review(config, context)

    app.state.runner.ai = Slow()
    try:
        first = client.post("/api/jobs", json=weekly_request())
        assert entered.wait(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda key: client.post("/api/jobs", json=weekly_request(key)),
                    ["parallel-one", "parallel-two"],
                )
            )
        assert all(r.json()["id"] == first.json()["id"] for r in responses)
        assert len(store.rows("SELECT * FROM jobs")) == 1
        store.save_entry(uid, "meal", meal("2026-10-17", 100))
    finally:
        release.set()
    assert finish(client, first)["result"]["stale"]


@pytest.mark.parametrize(
    "method,data",
    [
        ("cardio_estimate", {"effective_met": 99, "rationale": "错误", "assumptions": []}),
        ("weekly_review", {"summary": "缺少必要字段"}),
    ],
)
def test_ai_output_contract_rejects_bad_values(monkeypatch, method, data):
    monkeypatch.setattr(AIClient, "call", lambda *args: (data, {}))
    with pytest.raises(AIError):
        getattr(AIClient(), method)({"coach_model": "offline"}, {})


def test_coaching_tasks_recover_interrupted_without_automatic_retry(client, store):
    uid = register(client)["id"]
    store.save_profile(uid, profile("2026-10-15"))
    first, _ = store.create_job(uid, cardio_request())
    second, _ = store.create_job(uid, weekly_request())
    store.update_job(uid, first["id"], "running")
    store.recover_jobs()
    assert store.job(uid, first["id"])["status"] == "interrupted"
    assert store.job(uid, second["id"])["status"] == "interrupted"
    assert client.get("/api/days/2026-10-15").json()["exercise_kcal"] == 0
