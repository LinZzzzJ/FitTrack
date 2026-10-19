"""Explicit paid acceptance: two meal/feedback calls, or one --goals-only call."""

import argparse
import json
import tempfile
import time
import getpass
from contextlib import nullcontext
from pathlib import Path

from fastapi.testclient import TestClient

from fittrack.app import create_app
from fittrack.calculations import today
from fittrack.control import WorkspaceHub
from fittrack.credentials import CredentialStore
from fittrack.paths import RuntimePaths


def finished(client, jid):
    for _ in range(240):
        result = client.get(f"/api/jobs/{jid}").json()
        if result["status"] in {"done", "failed", "interrupted"}:
            assert result["status"] == "done", result.get("error")
            return result
        time.sleep(1)
    raise RuntimeError("AI job did not finish")


def check_goals(client, root, profile):
    response = client.post(
        "/api/jobs",
        json={
            "kind": "goals",
            "date": today(),
            "request_key": "live-goals-check",
            "goal_profile": {**profile, "target_weight_kg": 65},
        },
    )
    assert response.status_code == 202, response.text
    job = finished(client, response.json()["id"])
    goals = job["result"]["goals"]
    energy = goals["protein_target_g"] * 4 + goals["carbs_target_g"] * 4 + goals["fat_target_g"] * 9
    assert abs(energy - goals["calorie_target"]) <= max(20, goals["calorie_target"] * 0.02)
    assert not job["result"]["stale"]
    assert client.get("/api/me").json()["profile"] is None
    report = {
        "date": today(),
        "model": client.get("/api/me").json()["ai"]["coach_model"],
        "status": job["status"],
        "goals": goals,
        "basis": job["result"]["basis"],
        "macro_kcal": energy,
        "existing_profile_unchanged": True,
        "usage": job["result"]["usage"],
        "test_data": "isolated controlled test root; session-only credential",
    }
    artifacts = root / "caches" / "reports"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "live-goals-check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Only acceptance metadata goes to the terminal, never credentials.
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "date",
                    "model",
                    "status",
                    "existing_profile_unchanged",
                    "usage",
                )
            },
            ensure_ascii=False,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--goals-only", action="store_true")
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error("This performs billed AI requests; pass --allow-paid explicitly")
    root = Path(__file__).resolve().parents[1]
    key = getpass.getpass("Your API Key (hidden; test session only): ").strip()
    if not key:
        parser.error("A personal API key is required")
    checks = root / "artifacts" / "live"
    checks.mkdir(parents=True, exist_ok=True)
    with nullcontext(tempfile.mkdtemp(prefix="run-", dir=checks)) as directory:
        paths = RuntimePaths.initialize(Path(directory))
        paths.configure_process()
        store = WorkspaceHub(paths)
        settings = CredentialStore(store.control, paths)
        app = create_app(store, settings)
        try:
            with TestClient(app, base_url="http://127.0.0.1") as client:
                assert (
                    client.post(
                        "/api/auth/register",
                        json={
                            "username": "temporary-live-check",
                            "password": "temporary-test-password",
                        },
                    ).status_code
                    == 201
                )
                assert (
                    client.put(
                        "/api/settings", json={"api_key": key, "remember": False}
                    ).status_code
                    == 200
                )
                key = ""
                profile = {
                    "effective_date": today(),
                    "height_cm": 175,
                    "initial_weight_kg": 75,
                    "sex": "male",
                    "resting_kcal": 1800,
                    "activity_factor": 1.2,
                    "calorie_target": 2000,
                }
                if args.goals_only:
                    check_goals(client, paths.root, profile)
                    return
                assert client.put("/api/profile", json=profile).status_code == 200
                data = (root / "docs" / "references" / "参考图.jpg").read_bytes()
                image = client.post(
                    "/api/uploads", files={"file": ("reference.jpg", data, "image/jpeg")}
                ).json()
                request = {
                    "kind": "meal",
                    "date": today(),
                    "image_id": image["id"],
                    "note": "鸡蛋只吃蛋白，不吃蛋黄。虾去头去壳，只吃虾肉。",
                    "slot": "lunch",
                    "request_key": "live-meal-check",
                }
                job = client.post("/api/jobs", json=request)
                assert job.status_code == 202, job.text
                meal = finished(client, job.json()["id"])
                items = meal["result"]["items"]
                assert items and all(item["kcal"] >= 0 for item in items)
                assert any(
                    "蛋白" in (item["name"] + item["consumed_part"])
                    or "蛋清" in (item["name"] + item["consumed_part"])
                    for item in items
                )
                assert client.get(f"/api/days/{today()}").json()["totals"]["kcal"] == 0
                payload = {
                    "date": today(),
                    "slot": "lunch",
                    "title": "真实接口验收",
                    "note": request["note"],
                    "image_id": image["id"],
                    "source_job_id": meal["id"],
                    "items": items,
                }
                first = client.post("/api/meals", json=payload)
                duplicate = client.post("/api/meals", json=payload)
                assert first.status_code == 201 and first.json()["id"] == duplicate.json()["id"]
                feedback = client.post(
                    "/api/jobs",
                    json={
                        "kind": "feedback",
                        "date": today(),
                        "request_key": "live-feedback-check",
                    },
                )
                advice = finished(client, feedback.json()["id"])
                saved = client.get(f"/api/days/{today()}").json()
                assert saved["feedback"] and not saved["feedback"]["stale"]
                report = {
                    "date": today(),
                    "model": client.get("/api/me").json()["ai"]["vision_model"],
                    "meal": {
                        "status": meal["status"],
                        "item_count": len(items),
                        "kcal_sum": saved["totals"]["kcal"],
                        "eating_instructions_followed": True,
                        "usage": meal["result"]["usage"],
                    },
                    "feedback": {
                        "status": advice["status"],
                        "valid_schema": True,
                        "usage": advice["result"]["usage"],
                    },
                    "confirmation_idempotent": True,
                    "test_data": "isolated controlled test root; session-only credential",
                }
                artifacts = paths.root / "caches" / "reports"
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / "live-check.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(json.dumps(report, ensure_ascii=False))
        finally:
            store.close()


if __name__ == "__main__":
    main()
