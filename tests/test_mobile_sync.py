import copy
import json

import pytest
from fastapi.testclient import TestClient

from conftest import FakeAI, meal, profile, register
from fittrack.app import create_app
from fittrack.control import WorkspaceHub
from fittrack.credentials import CredentialStore
from fittrack.paths import RuntimePaths
from fittrack.mobile_sync import merge


@pytest.fixture
def mobile(tmp_path):
    paths = RuntimePaths.initialize(tmp_path / "sync-root")
    hub = WorkspaceHub(paths)
    app = create_app(
        hub,
        CredentialStore(hub.control, paths),
        ai=FakeAI(),
        allowed_hosts={"testserver", "localhost"},
    )
    with TestClient(app) as client:
        yield client, hub
    hub.close()


def test_three_way_merges_disjoint_fields_and_keeps_conflict():
    base = {"weight": 75, "note": "base", "sets": [1]}
    assert merge(base, base | {"weight": 74}, base | {"note": "pc"}) == (
        {"weight": 74, "note": "pc", "sets": [1]},
        False,
    )
    value, conflict = merge(base, base | {"weight": 73}, base | {"weight": 76})
    assert conflict and value["weight"] == 76
    assert merge(base, None, base) == (None, False)
    assert merge(base, None, base | {"note": "edited"})[1]


def test_sync_detects_pc_writes_and_tombstones(mobile):
    client, hub = mobile
    uid = register(client)["id"]
    client.put("/api/profile", json=profile())
    first = client.get("/api/mobile/sync").json()
    assert first["changes"][0]["resource"] == "profiles/2026-10-14"
    body = {"date": "2026-10-20", "weight_kg": 74}
    assert client.put("/api/body", json=body).status_code == 200
    second = client.get("/api/mobile/sync", params={"cursor": first["cursor"]}).json()
    assert second["changes"][0]["row"]["user_id"] == uid
    assert client.delete("/api/body/2026-10-20").status_code == 204
    third = client.get("/api/mobile/sync", params={"cursor": second["cursor"]}).json()
    assert third["changes"] == [{"resource": "bodies/2026-10-20", "row": None}]


def test_push_idempotency_conflict_and_account_isolation(mobile):
    client, hub = mobile
    uid = register(client)["id"]
    row = {
        "user_id": uid,
        "date": "2026-10-20",
        "data": json.dumps(
            {
                "date": "2026-10-20",
                "weight_kg": 74,
                "body_fat_pct": None,
                "resting_kcal": None,
                "note": "",
            }
        ),
    }
    change = {"id": "a" * 24, "table": "bodies", "key": row["date"], "base": None, "row": row}
    response = client.post("/api/mobile/sync", json={"changes": [change]})
    assert response.status_code == 200, response.text
    assert client.post("/api/mobile/sync", json={"changes": [change]}).status_code == 200
    assert hub.rows("SELECT COUNT(*) AS n FROM bodies WHERE user_id=?", (uid,))[0]["n"] == 1
    remote = copy.deepcopy(row)
    remote["data"] = json.dumps(json.loads(row["data"]) | {"weight_kg": 76})
    client.put("/api/body", json=json.loads(remote["data"]))
    local = copy.deepcopy(row)
    local["data"] = json.dumps(json.loads(row["data"]) | {"weight_kg": 73})
    conflict = client.post(
        "/api/mobile/sync", json={"changes": [dict(change, id="b" * 24, base=row, row=local)]}
    )
    assert conflict.status_code == 200, conflict.text
    assert conflict.json()["acknowledgements"][0]["conflict_id"]
    assert hub.body(uid, row["date"])["weight_kg"] == 76
    conflicts = client.get("/api/mobile/conflicts").json()
    assert json.loads(conflicts[0]["local"]["data"])["weight_kg"] == 73
    register(client, "other-user")
    assert client.get("/api/mobile/conflicts").json() == []
    assert client.post("/api/mobile/sync", json={"changes": [change]}).status_code == 400


def test_sync_recalculates_precise_energy_and_rolls_back_bad_rows(mobile):
    client, hub = mobile
    uid = register(client)["id"]
    payload = meal()
    payload.update(nutrition_mode="precise", meal_description="synthetic")
    payload["items"][0].update(protein_g=10, carbs_g=20, fat_g=5, kcal=999)
    row = {
        "id": "c" * 24,
        "user_id": uid,
        "kind": "meal",
        "date": payload["date"],
        "data": json.dumps(payload),
        "source_job_id": None,
        "plan_id": None,
        "created_at": 1,
    }
    change = {"id": "d" * 24, "table": "entries", "key": row["id"], "row": row}
    response = client.post("/api/mobile/sync", json={"changes": [change]})
    assert response.status_code == 200, response.text
    assert hub.entry(uid, "meal", row["id"])["items"][0]["kcal"] == 165
    bad = dict(change, id="e" * 24, table="sessions")
    assert client.post("/api/mobile/sync", json={"changes": [bad]}).status_code == 400
    assert hub.entry(uid, "meal", row["id"])["items"][0]["kcal"] == 165


def test_workspace_epoch_detects_restored_database(mobile):
    client, hub = mobile
    uid = register(client)["id"]
    client.put("/api/profile", json=profile())
    first = client.get("/api/mobile/sync").json()
    hub.for_user(uid).db.execute(
        "UPDATE mobile_sync_meta SET value='new-workspace' WHERE key='epoch'"
    )
    assert (
        client.get(
            "/api/mobile/sync", params={"cursor": first["cursor"], "epoch": first["epoch"]}
        ).status_code
        == 409
    )
    assert client.get("/api/mobile/sync", params={"cursor": 0}).json()["epoch"] == "new-workspace"


def test_server_registration_closed_and_login_throttled_by_default(mobile):
    from fittrack.runtime import RuntimeConfig

    client, hub = mobile
    register(client, "server-owner")
    app = create_app(
        hub,
        CredentialStore(hub.control, hub.paths, "server"),
        ai=FakeAI(),
        runtime_config=RuntimeConfig("server", "https://fitness.example"),
    )
    with TestClient(app, base_url="https://fitness.example") as browser:
        assert (
            browser.post(
                "/api/auth/register",
                json={"username": "uninvited", "password": "synthetic-password"},
            ).status_code
            == 403
        )
        for _ in range(10):
            assert (
                browser.post(
                    "/api/auth/login",
                    json={"username": "unknown", "password": "synthetic-password"},
                ).status_code
                == 401
            )
        assert (
            browser.post(
                "/api/auth/login", json={"username": "unknown", "password": "synthetic-password"}
            ).status_code
            == 429
        )
