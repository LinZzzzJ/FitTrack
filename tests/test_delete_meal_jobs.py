import json

import pytest
from fastapi.testclient import TestClient

from conftest import meal, picture, profile, register
from fittrack.models import JobRequest
from fittrack.store import encode
from test_diet_labels_version import label_snapshot


def analysis(store, uid, *, status="done", mode="photo", kind="meal"):
    image = store.put_image(uid, picture())
    request = JobRequest(
        kind=kind,
        date="2026-10-14",
        image_id=image["id"],
        meal_mode=mode,
        slot="lunch",
        request_key=f"delete-{kind}-{mode}-{status}",
    ).model_dump(mode="json")
    job, _ = store.create_job(uid, request)
    result = {"label": label_snapshot()["label"]} if mode == "label" else {"items": meal()["items"]}
    store.update_job(uid, job["id"], status, result=result if status == "done" else None)
    return store.job(uid, job["id"]), image


@pytest.mark.parametrize("mode", ["photo", "label"])
def test_delete_analysis_preserves_booked_meal_and_image(client, app, mode, monkeypatch):
    uid = register(client)["id"]
    store = app.state.store
    client.put("/api/profile", json=profile())
    job, image = analysis(store, uid, mode=mode)
    payload = meal() | {"source_job_id": job["id"], "image_id": image["id"]}
    if mode == "label":
        payload["nutrition_label"] = label_snapshot()
    saved = client.post("/api/meals", json=payload).json()
    # The saved meal may have been moved to another day after recognition.
    saved = client.put(f"/api/meals/{saved['id']}", json=payload | {"date": "2026-10-15"}).json()
    before = client.get("/api/days/2026-10-15").json()
    fingerprint = store.fingerprint(uid, "2026-10-15")
    image_bytes = client.get(f"/api/images/{image['id']}").content
    events = []
    monkeypatch.setattr(app.state.bus, "publish", lambda user, event: events.append((user, event)))
    response = client.delete(f"/api/jobs/{job['id']}")
    assert response.status_code == 204 and not response.content
    assert events == [(uid, {"type": "job_deleted", "id": job["id"], "date": job["date"]})]
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 404
    after = client.get("/api/days/2026-10-15").json()
    assert after["meals"] == [before["meals"][0] | {"source_job_id": None}]
    assert (after["totals"], after["deficit_kcal"]) == (before["totals"], before["deficit_kcal"])
    assert store.fingerprint(uid, "2026-10-15") == fingerprint
    row = store.one("SELECT * FROM entries WHERE user_id=? AND id=?", (uid, saved["id"]))
    assert row["source_job_id"] is None and json.loads(row["data"])["source_job_id"] is None
    assert client.get(f"/api/images/{image['id']}").content == image_bytes
    updated = client.put(
        f"/api/meals/{saved['id']}",
        json=payload | {"date": "2026-10-15", "source_job_id": None, "note": "still editable"},
    )
    assert updated.status_code == 200, updated.text
    history = client.get("/api/diet-history?start=2026-10-08&end=2026-10-14").json()
    assert all(not day["jobs"] for day in history["days"])


@pytest.mark.parametrize("mode", ["photo", "label"])
@pytest.mark.parametrize("status", ["done", "failed", "interrupted"])
def test_delete_unbooked_analysis_permanently(client, app, mode, status):
    uid = register(client)["id"]
    job, image = analysis(app.state.store, uid, mode=mode, status=status)
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert not client.get("/api/days/2026-10-14").json()["jobs"]
    assert client.get(f"/api/images/{image['id']}").status_code == 200


@pytest.mark.parametrize("status", ["queued", "running"])
def test_active_analysis_cannot_be_deleted(client, app, status):
    uid = register(client)["id"]
    job, _ = analysis(app.state.store, uid, status=status)
    result = client.delete(f"/api/jobs/{job['id']}")
    assert result.status_code == 409 and "等待" in result.json()["detail"]
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == status


def test_analysis_delete_requires_owner_and_meal_kind(client, app):
    uid = register(client)["id"]
    job, _ = analysis(app.state.store, uid)
    other = TestClient(app)
    try:
        assert other.delete(f"/api/jobs/{job['id']}").status_code == 401
        register(other, "bob")
        assert other.delete(f"/api/jobs/{job['id']}").status_code == 404
    finally:
        other.close()
    assert client.get(f"/api/jobs/{job['id']}").status_code == 200
    client.put("/api/profile", json=profile())
    feedback, _ = analysis(app.state.store, uid, kind="feedback")
    assert client.delete(f"/api/jobs/{feedback['id']}").status_code == 404
    assert client.get(f"/api/jobs/{feedback['id']}").status_code == 200


def test_analysis_delete_rolls_back_all_changes_if_delete_fails(client, app):
    uid = register(client)["id"]
    store = app.state.store
    job, image = analysis(store, uid)
    client.post("/api/meals", json=meal() | {"source_job_id": job["id"], "image_id": image["id"]})
    before = encode(store.rows("SELECT * FROM entries WHERE user_id=?", (uid,)))
    store.db.execute(
        "CREATE TRIGGER reject_job_delete BEFORE DELETE ON jobs BEGIN SELECT RAISE(ABORT, 'test failure'); END"
    )
    try:
        assert client.delete(f"/api/jobs/{job['id']}").status_code == 409
        assert encode(store.rows("SELECT * FROM entries WHERE user_id=?", (uid,))) == before
        assert client.get(f"/api/jobs/{job['id']}").status_code == 200
    finally:
        store.db.execute("DROP TRIGGER reject_job_delete")


def test_completed_job_deleted_before_worker_notification_does_not_fail(client, app, monkeypatch):
    uid = register(client)["id"]
    store = app.state.store
    job, image = analysis(store, uid, status="queued")
    original = store.update_job

    def complete_then_delete(user, jid, status, **kwargs):
        original(user, jid, status, **kwargs)
        if status == "done":
            store.delete_job(user, jid)

    monkeypatch.setattr(store, "update_job", complete_then_delete)
    app.state.runner._run(uid, job, store.image_path(uid, image["id"]), None, {})
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
