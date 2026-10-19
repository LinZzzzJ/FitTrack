import json
import threading
import time

import pytest
import requests

from fittrack.ai import AIClient, AIError
from fittrack.config import Settings
from fittrack.events import EventBus
from fittrack.jobs import JobRunner

from conftest import FakeAI, picture, profile, register


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body
        self.closed = False

    def iter_content(self, chunk_size):
        yield json.dumps(self.body).encode("utf-8")

    def close(self):
        self.closed = True


def test_provider_errors_do_not_expose_sensitive_response(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **kw: FakeResponse(401, {"error": "private-provider-message secret-token"}),
    )
    config = {"base_url": "https://invalid.example", "api_key": "test-only-key"}
    with pytest.raises(AIError) as error:
        AIClient().call(config, "test-model", [], 10)
    assert "secret-token" not in str(error.value)
    assert "认证失败" in str(error.value)


def test_invalid_json_and_truncated_response(monkeypatch):
    config = {"base_url": "https://invalid.example", "api_key": "test-only-key"}
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **kw: FakeResponse(
            200, {"choices": [{"message": {"content": "not JSON"}, "finish_reason": "stop"}]}
        ),
    )
    with pytest.raises(AIError, match="JSON"):
        AIClient().call(config, "test-model", [], 10)
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **kw: FakeResponse(
            200, {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}
        ),
    )
    with pytest.raises(AIError, match="截断"):
        AIClient().call(config, "test-model", [], 10)


def test_timeout_has_no_automatic_retry(monkeypatch):
    attempts = []

    def timeout(*args, **kwargs):
        attempts.append(True)
        raise requests.Timeout()

    monkeypatch.setattr(requests, "post", timeout)
    with pytest.raises(AIError, match="超时"):
        AIClient().call(
            {"base_url": "https://invalid.example", "api_key": "test-only-key"}, "test", [], 10
        )
    assert len(attempts) == 1


def test_keep_alive_whitespace_has_total_wait_limit_and_closes(monkeypatch):
    from fittrack import ai

    class QueueResponse(FakeResponse):
        def iter_content(self, chunk_size):
            yield b"\n"
            yield b"\n"

    response = QueueResponse(200, {})
    attempts = []
    ticks = iter([0, 10, 121])
    monkeypatch.setattr(ai.time, "monotonic", lambda: next(ticks))

    def queued(*args, **kwargs):
        attempts.append(kwargs)
        return response

    monkeypatch.setattr(requests, "post", queued)
    with pytest.raises(AIError, match="两分钟"):
        AIClient().call(
            {"base_url": "https://invalid.example", "api_key": "test-only"}, "test", [], 10
        )
    assert len(attempts) == 1 and attempts[0]["stream"] is True
    assert response.closed


def test_json_after_keep_alive_lines_parses_and_closes(monkeypatch):
    class QueuedThenReady(FakeResponse):
        def iter_content(self, chunk_size):
            yield b"\n\n"
            yield from super().iter_content(chunk_size)

    response = QueuedThenReady(
        200,
        {
            "choices": [{"message": {"content": '{"summary":"ready"}'}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 10},
        },
    )
    monkeypatch.setattr(requests, "post", lambda *a, **kw: response)
    result, usage = AIClient().call(
        {"base_url": "https://invalid.example", "api_key": "test-only"}, "test", [], 10
    )
    assert result == {"summary": "ready"} and usage["total_tokens"] == 10
    assert response.closed


def test_body_resting_override_and_deleted_measurement(client):
    register(client)
    client.put("/api/profile", json=profile())
    client.put("/api/body", json={"date": "2026-10-14", "weight_kg": 74, "resting_kcal": 1900})
    assert client.get("/api/days/2026-10-14").json()["baseline_kcal"] == 2280
    client.delete("/api/body/2026-10-14")
    assert client.get("/api/days/2026-10-14").json()["effective_weight_kg"] == 75
    assert (
        client.post(
            "/api/uploads", files={"file": ("invalid.jpg", b"not an image", "image/jpeg")}
        ).status_code
        == 400
    )


def test_restart_marks_pending_jobs_interrupted(store):
    uid = store.register("recovery", "hash-placeholder")["id"]
    request = {
        "kind": "meal",
        "date": "2026-10-14",
        "request_key": "recover-test-1",
        "image_id": None,
        "note": "",
        "slot": "lunch",
    }
    job, _ = store.create_job(uid, request)
    store.update_job(uid, job["id"], "running")
    store.recover_jobs()
    assert store.job(uid, job["id"])["status"] == "interrupted"


def test_record_change_during_feedback_and_ordering(store, tmp_path):
    started, release = threading.Event(), threading.Event()

    class WaitingAI(FakeAI):
        def feedback(self, config, context):
            started.set()
            assert release.wait(timeout=5)
            return super().feedback(config, context)

    uid = store.register("feedback-race", "hash-placeholder")["id"]
    store.save_profile(uid, profile())
    env = tmp_path / "test.env"
    env.write_text("FITTRACK_AI_API_KEY=test-only\n", encoding="utf-8")
    runner = JobRunner(store, Settings(env), EventBus(), WaitingAI())
    try:
        request = {
            "kind": "feedback",
            "date": "2026-10-14",
            "request_key": "race-test-1",
            "note": "",
            "slot": "lunch",
            "image_id": None,
        }
        job = runner.submit(uid, request)
        assert started.wait(timeout=5)
        store.save_body(
            uid,
            {
                "date": "2026-10-14",
                "weight_kg": 73,
                "body_fat_pct": None,
                "resting_kcal": None,
                "note": "updated",
            },
        )
        release.set()
        for _ in range(100):
            if store.job(uid, job["id"])["status"] == "done":
                break
            time.sleep(0.01)
        assert store.feedback(uid, "2026-10-14")["stale"]
        newer = {"summary": "newer result"}
        fingerprint = store.fingerprint(uid, "2026-10-14")
        store.save_feedback(uid, "2026-10-14", newer, fingerprint, 9999999999)
        store.save_feedback(uid, "2026-10-14", {"summary": "older result"}, fingerprint, 1)
        assert store.feedback(uid, "2026-10-14")["data"] == newer
    finally:
        release.set()
        runner.shutdown()


def test_failed_analysis_keeps_image_and_request(store, tmp_path):
    class FailingAI(FakeAI):
        def meal(self, config, path, note):
            raise AIError("模拟网络失败")

    uid = store.register("failed-job", "hash-placeholder")["id"]
    image = store.put_image(uid, picture())
    env = tmp_path / "test.env"
    env.write_text("FITTRACK_AI_API_KEY=test-only\n", encoding="utf-8")
    runner = JobRunner(store, Settings(env), EventBus(), FailingAI())
    try:
        request = {
            "kind": "meal",
            "date": "2026-10-14",
            "request_key": "failed-test-1",
            "image_id": image["id"],
            "note": "只吃蛋白",
            "slot": "lunch",
        }
        job = runner.submit(uid, request)
        for _ in range(100):
            failed = store.job(uid, job["id"])
            if failed["status"] == "failed":
                break
            time.sleep(0.01)
        assert failed["status"] == "failed"
        assert failed["request"]["note"] == "只吃蛋白"
        assert store.image_path(uid, image["id"]).exists()
        assert store.summary(uid, "2026-10-14")["totals"]["kcal"] == 0
    finally:
        runner.shutdown()


def test_settings_never_return_key_and_preserve_existing(client):
    register(client)
    response = client.put("/api/settings", json={"base_url": "https://api.deepseek.com"})
    assert response.status_code == 200
    assert response.json()["api_key_set"] is True
    assert "test-only-placeholder" not in response.text
    assert (
        client.put("/api/settings", json={"base_url": "https://host.example\ninvalid"}).status_code
        == 400
    )


def test_private_records_and_images_are_not_cached(client):
    register(client)
    image = client.post("/api/uploads", files={"file": ("food.png", picture(), "image/png")}).json()
    assert "no-store" in client.get(f"/api/images/{image['id']}").headers["cache-control"]
    assert "no-store" in client.get("/api/me").headers["cache-control"]
