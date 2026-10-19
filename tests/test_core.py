import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from fittrack.calculations import nutrients, workout_energy
from fittrack.config import lock_home
from fittrack.events import EventBus
from fittrack.store import Store

from conftest import food, meal, picture, profile, register


def wait_job(client, jid):
    for _ in range(100):
        job = client.get(f"/api/jobs/{jid}").json()
        if job["status"] in {"done", "failed"}:
            return job
        time.sleep(0.01)
    raise AssertionError("Job did not finish")


def test_auth_security(client, app, store):
    assert client.get("/api/me").status_code == 401
    alice = register(client)
    assert alice["is_admin"]
    assert "password" not in str(alice)
    hashed = store.rows("SELECT password_hash FROM users")[0]["password_hash"]
    assert hashed.startswith("$argon2")
    cookie = client.cookies.get("fittrack_session")
    assert cookie not in str(store.rows("SELECT token_hash FROM sessions"))
    assert (
        client.post(
            "/api/auth/register", json={"username": "ALICE", "password": "test-password-123"}
        ).status_code
        == 409
    )
    assert client.get("/api/me", headers={"host": "evil.example"}).status_code == 403
    assert (
        client.put(
            "/api/profile", json=profile(), headers={"origin": "https://evil.example"}
        ).status_code
        == 403
    )
    with TestClient(app) as bob:
        user = register(bob, "bob")
        assert not user["is_admin"]
        assert bob.put("/api/settings", json={"api_key": "unwanted"}).status_code == 403
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong-password"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"username": "alice", "password": "test-password-123"}
        ).status_code
        == 200
    )


def test_calculation_acceptance_and_backfill(client):
    register(client)
    assert client.put("/api/profile", json=profile()).status_code == 200
    assert client.post("/api/meals", json=meal()).status_code == 201
    workout = {
        "date": "2026-10-14",
        "title": "力量训练",
        "duration_minutes": 60,
        "met": 6,
        "exercises": [
            {"name": "深蹲", "sets": [{"reps": 10, "weight_kg": 60}, {"reps": 8, "weight_kg": 65}]}
        ],
    }
    assert client.post("/api/workouts", json=workout).status_code == 201
    summary = client.get("/api/days/2026-10-14").json()
    assert summary["deficit_kcal"] == 535
    assert summary["volume_kg"] == 1120
    client.put("/api/body", json={"date": "2026-10-13", "weight_kg": 70})
    assert client.get("/api/days/2026-10-14").json()["exercise_kcal"] == 345
    client.put("/api/body", json={"date": "2026-10-15", "weight_kg": 90})
    assert client.get("/api/days/2026-10-14").json()["effective_weight_kg"] == 70
    newer = profile("2026-10-15") | {"resting_kcal": 2000}
    client.put("/api/profile", json=newer)
    assert client.get("/api/days/2026-10-14").json()["resting_kcal"] == 1800
    assert client.get("/api/days/2026-10-15").json()["resting_kcal"] == 2000


def test_nulls_and_validation(client):
    register(client)
    client.put("/api/profile", json=profile())
    assert client.put("/api/body", json={"date": "2026-10-14", "weight_kg": 75}).status_code == 200
    assert client.put("/api/body", json={"date": "2026-10-14"}).status_code == 400
    assert client.post("/api/meals", json=meal() | {"items": [food(-10)]}).status_code == 422
    assert (
        client.post(
            "/api/workouts", json={"date": "2026-10-14", "title": "测试", "duration_minutes": 0}
        ).status_code
        == 422
    )
    rows = client.get("/api/trends?start=2026-10-13&end=2026-10-15").json()["days"]
    assert rows[0]["body"] is None
    assert rows[1]["body"]["body_fat_pct"] is None
    assert client.get("/api/trends?start=2025-01-01&end=2026-10-15").status_code == 400


def test_ownership_and_image_access(client, app):
    register(client)
    image = client.post("/api/uploads", files={"file": ("meal.png", picture(), "image/png")}).json()
    record = client.post("/api/meals", json=meal() | {"image_id": image["id"]}).json()
    assert client.get(f"/api/images/{image['id']}?thumb=true").status_code == 200
    with TestClient(app) as bob:
        register(bob, "bob")
        assert bob.get(f"/api/images/{image['id']}").status_code == 404
        assert bob.put(f"/api/meals/{record['id']}", json=meal()).status_code == 404
        assert bob.delete(f"/api/meals/{record['id']}").status_code == 404
        assert bob.post("/api/meals", json=meal() | {"image_id": image["id"]}).status_code == 404
        assert not bob.get("/api/days/2026-10-14").json()["meals"]


def test_jobs_idempotency_feedback_and_plan(client):
    register(client)
    client.put("/api/profile", json=profile())
    image = client.post("/api/uploads", files={"file": ("meal.png", picture(), "image/png")}).json()
    request = {
        "kind": "meal",
        "date": "2026-10-14",
        "image_id": image["id"],
        "note": "只吃蛋白",
        "request_key": "meal-request-1",
    }
    job = client.post("/api/jobs", json=request).json()
    assert client.post("/api/jobs", json=request).json()["id"] == job["id"]
    done = wait_job(client, job["id"])
    assert done["status"] == "done"
    assert client.get("/api/days/2026-10-14").json()["totals"]["kcal"] == 0
    payload = meal(kcal=52) | {
        "image_id": image["id"],
        "source_job_id": job["id"],
        "items": done["result"]["items"],
    }
    saved = client.post("/api/meals", json=payload).json()
    assert client.post("/api/meals", json=payload).json()["id"] == saved["id"]
    feedback = client.post(
        "/api/jobs",
        json={"kind": "feedback", "date": "2026-10-14", "request_key": "feedback-request-1"},
    ).json()
    assert wait_job(client, feedback["id"])["status"] == "done"
    assert client.get("/api/days/2026-10-14").json()["feedback"]["stale"] is False
    client.put("/api/body", json={"date": "2026-10-14", "weight_kg": 74})
    assert client.get("/api/days/2026-10-14").json()["feedback"]["stale"] is True
    plan = client.post("/api/plans", json={"date": "2026-10-14", "title": "上肢训练"}).json()
    assert client.get("/api/days/2026-10-14").json()["exercise_kcal"] == 0
    actual = client.post(f"/api/plans/{plan['id']}/complete").json()
    assert client.post(f"/api/plans/{plan['id']}/complete").json()["id"] == actual["id"]
    assert (
        client.get("/api/plans?start=2026-10-14&end=2026-10-14").json()[0]["status"] == "completed"
    )
    assert client.delete(f"/api/workouts/{actual['id']}").status_code == 204
    assert client.get("/api/plans?start=2026-10-14&end=2026-10-14").json()[0]["status"] == "planned"


def test_concurrent_storage_and_reopen(store, tmp_path):
    uid = store.register("account", "hash-placeholder")["id"]
    with ThreadPoolExecutor(max_workers=5) as pool:
        ids = list(pool.map(lambda i: store.save_entry(uid, "meal", meal(kcal=i))["id"], range(20)))
    assert len(set(ids)) == 20
    assert len(store.entries(uid, "meal", "2026-10-14", "2026-10-14")) == 20
    second = Store(store.home)
    assert len(second.entries(uid, "meal", "2026-10-14", "2026-10-14")) == 20
    second.close()
    handle = lock_home(tmp_path / "lock-test")
    with pytest.raises(RuntimeError):
        lock_home(tmp_path / "lock-test")
    handle.close()


def test_user_event_isolation():
    async def check():
        bus = EventBus()
        bus.bind(asyncio.get_running_loop())
        alice, bob = bus.subscribe("alice"), bus.subscribe("bob")
        bus.publish("alice", {"id": "private-job"})
        await asyncio.sleep(0.01)
        assert (await alice.get())["id"] == "private-job"
        assert bob.empty()
        bus.close()

    asyncio.run(check())


def test_zero_macros_and_zero_override():
    assert nutrients([food() | {"protein_g": 0, "carbs_g": 0, "fat_g": 0}])["macro_percent"] == {
        "protein": 0,
        "carbs": 0,
        "fat": 0,
    }
    workout = {
        "activity": "strength",
        "duration_minutes": 60,
        "intensity": "vigorous",
        "net_kcal_override": 0,
    }
    assert workout_energy(workout, 75, 1800)["net_kcal"] == 0
