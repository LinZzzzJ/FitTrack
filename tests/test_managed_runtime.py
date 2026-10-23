"""Acceptance for controlled paths, per-account secrets and reversible data moves."""

import json
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import FakeAI, meal, picture, profile, register
from fittrack.app import create_app
from fittrack.control import WorkspaceHub
from fittrack.credentials import CredentialStore
from fittrack.paths import RuntimePaths
from fittrack.relocation import relocate_root
from fittrack.routes import COOKIE, password_hash
from fittrack.runtime import RuntimeConfig
from fittrack.storage_ops import StorageOperations, verify_store
from fittrack.store import Store
from fittrack.upgrade import import_legacy


@pytest.fixture
def managed(tmp_path, monkeypatch):
    paths = RuntimePaths.initialize(tmp_path / "chosen-root")
    monkeypatch.setattr(tempfile, "tempdir", str(paths.root / "tmp"))
    hub = WorkspaceHub(paths)
    vault = CredentialStore(hub.control, paths)
    app = create_app(hub, vault, ai=FakeAI(), allowed_hosts={"testserver", "127.0.0.1"})
    with TestClient(app) as client:
        yield client, app, hub, vault, paths
    hub.close()


def wait_operation(client, response):
    assert response.status_code == 202, response.text
    ident = response.json()["id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get(f"/api/storage/operations/{ident}").json()
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(0.01)
    raise AssertionError("data operation timed out")


def test_controlled_root_rejects_unmarked_and_reserved_paths(tmp_path):
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "existing.txt").write_text("preserve")
    with pytest.raises(ValueError, match="空文件夹"):
        RuntimePaths.initialize(dirty)
    with pytest.raises(ValueError, match="绝对"):
        RuntimePaths.initialize(Path("relative"))
    paths = RuntimePaths.initialize(tmp_path / "root")
    for path in (
        "../escape",
        str(tmp_path / "outside"),
        "control/health",
        "secrets/health",
        "records",
    ):
        with pytest.raises(ValueError):
            paths.workspace(path)
    assert paths.workspace("personal/alice") == paths.root / "personal" / "alice"
    assert RuntimePaths.initialize(paths.root).identity == paths.identity


def test_process_tmp_has_no_fallback(tmp_path, monkeypatch):
    import os
    import sys

    paths = RuntimePaths.initialize(tmp_path / "root")
    for key in ("TMP", "TEMP", "TMPDIR", "SQLITE_TMPDIR", "PYTHONDONTWRITEBYTECODE", "PSModuleAnalysisCachePath"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    monkeypatch.setattr(tempfile, "tempdir", tempfile.tempdir)
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    paths.configure_process()
    with tempfile.NamedTemporaryFile() as stream:
        assert Path(stream.name).parent == paths.root / "tmp"
    (paths.root / "tmp").rmdir()
    with pytest.raises(FileNotFoundError):
        tempfile.NamedTemporaryFile()


def test_missing_key_never_overwrites_ciphertext(managed):
    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    client.put("/api/settings", json={"api_key": "synthetic-alice-key"})
    before = vault._row(uid)["ciphertext"]
    vault.keyfile.unlink()
    restarted = CredentialStore(hub.control, paths)
    assert not restarted.keyfile.exists()
    assert "主密钥" in restarted.public_for(uid)["credential_error"]
    assert client.get("/api/days/2026-10-14").status_code == 200
    assert (
        client.put("/api/settings", json={"base_url": "https://api.deepseek.com"}).status_code
        == 400
    )
    assert vault._row(uid)["ciphertext"] == before
    response = client.put("/api/settings", json={"api_key": "temporary-only", "remember": False})
    assert response.status_code == 200
    assert response.json()["credential_scope"] == "session"


def test_credentials_encrypted_scoped_and_no_default(managed, monkeypatch):
    client, app, hub, vault, paths = managed
    alice = register(client)
    monkeypatch.setenv("FITTRACK_AI_API_KEY", "must-never-be-a-fallback")
    assert not client.get("/api/me").json()["ai"]["api_key_set"]
    saved = client.put("/api/settings", json={"api_key": "synthetic-alice-key", "remember": True})
    assert saved.status_code == 200
    assert "synthetic" not in saved.text
    assert "api_key" not in saved.json()
    assert saved.json()["credential_scope"] == "account"
    assert vault._row(alice["id"])["ciphertext"].startswith("gAAAA")
    assert "synthetic-alice-key" not in str(hub.control.rows("SELECT * FROM ai"))
    bob = TestClient(app)
    try:
        bob_user = register(bob, "bob")
        assert not bob.get("/api/me").json()["ai"]["api_key_set"]
        assert bob.put("/api/settings", json={"api_key": "synthetic-bob-key"}).status_code == 200
        assert vault.snapshot_for(alice["id"])["api_key"] == "synthetic-alice-key"
        assert vault.snapshot_for(bob_user["id"])["api_key"] == "synthetic-bob-key"
        restarted = CredentialStore(hub.control, paths)
        assert restarted.snapshot_for(alice["id"])["api_key"] == "synthetic-alice-key"
        assert client.delete("/api/settings/key").status_code == 204
        assert not client.get("/api/me").json()["ai"]["api_key_set"]
        assert bob.get("/api/me").json()["ai"]["api_key_set"]
    finally:
        bob.close()


@pytest.mark.parametrize("expire", [False, True])
def test_session_key_logout_expiry_and_restart(managed, expire):
    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    token = client.cookies.get(COOKIE)
    assert (
        client.put("/api/settings", json={"api_key": "memory-only", "remember": False}).status_code
        == 200
    )
    assert vault._row(uid)["ciphertext"] is None
    assert vault.snapshot_for(uid, token)["api_key"] == "memory-only"
    assert not vault.snapshot_for(uid, "other-login")["api_key"]
    assert not CredentialStore(hub.control, paths).snapshot_for(uid, token)["api_key"]
    if expire:
        hub.control.db.execute("UPDATE sessions SET expires_at=0")
        assert client.get("/api/me").status_code == 401
    else:
        assert client.post("/api/auth/logout").status_code == 204
    assert not vault.snapshot_for(uid, token)["api_key"]
    assert not vault._memory


def test_connection_check_uses_models_and_redacts_errors(managed, monkeypatch):
    import requests

    client, app, hub, vault, paths = managed
    register(client)
    client.put("/api/settings", json={"api_key": "synthetic-key"})
    calls = []

    class Reply:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def json(self):
            return {"data": [{"id": "deepseek-flash"}]}

    def get(url, **kwargs):
        calls.append(url)
        return Reply()

    monkeypatch.setattr(requests, "get", get)
    response = client.post("/api/settings/test-connection")
    assert response.json()["models_available"]
    assert calls == ["https://api.deepseek.com/models"]

    def broken(*args, **kwargs):
        raise requests.ConnectionError("synthetic-key must not leak")

    monkeypatch.setattr(requests, "get", broken)
    response = client.post("/api/settings/test-connection")
    assert response.status_code == 400
    assert "synthetic" not in response.text


def test_workspaces_images_jobs_and_operations_are_isolated(managed):
    client, app, hub, vault, paths = managed
    alice = register(client)
    uid = alice["id"]
    client.put("/api/profile", json=profile())
    image = client.post("/api/uploads", files={"file": ("test.png", picture(), "image/png")}).json()
    entry = client.post("/api/meals", json=meal()).json()
    op = wait_operation(client, client.post("/api/backups"))
    bob = TestClient(app)
    try:
        other = register(bob, "bob")
        assert hub.for_user(uid).home != hub.for_user(other["id"]).home
        assert not bob.get("/api/me").json()["profile"]
        assert bob.get(f"/api/images/{image['id']}").status_code == 404
        assert bob.delete(f"/api/meals/{entry['id']}").status_code == 404
        assert bob.get(f"/api/storage/operations/{op['id']}").status_code == 404
        assert (
            bob.post(
                "/api/backups/restore", json={"backup_id": op["result"]["backup_id"]}
            ).status_code
            == 404
        )
        own_path = hub.workspace_relative(uid)
        assert bob.post("/api/storage/migrate", json={"path": own_path}).status_code == 400
        assert bob.post("/api/local/stop").status_code == 403
        assert not bob.get("/api/me").json()["runtime"]["migrate_root"]
        assert {
            row["name"]
            for row in hub.control.rows("SELECT name FROM sqlite_master WHERE type='table'")
        } >= {"users", "ai", "workspaces"}
        assert not hub.for_user(uid).rows(
            "SELECT name FROM sqlite_master WHERE name IN ('users','sessions','ai')"
        )
    finally:
        bob.close()


def test_backup_migration_restore_preserves_originals(managed):
    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    client.put("/api/profile", json=profile())
    image = client.post("/api/uploads", files={"file": ("test.png", picture(), "image/png")}).json()
    client.post("/api/meals", json=meal())
    client.put("/api/settings", json={"api_key": "never-in-health-backup"})
    before = verify_store(hub.for_user(uid), uid)
    original = hub.for_user(uid).home
    operation = wait_operation(client, client.post("/api/backups"))
    assert operation["status"] == "done", operation.get("error")
    bid = operation["result"]["backup_id"]
    backup = app.state.storage_ops.backup_path(uid, bid)
    assert backup.is_relative_to(paths.root / "backups" / uid)
    with zipfile.ZipFile(backup) as archive:
        manifest = archive.read("manifest.json").decode()
        assert all(
            value not in manifest
            for value in ("never-in-health-backup", "password_hash", "ciphertext", "master.key")
        )
        assert set(json.loads(manifest)["tables"]) == {
            "profiles",
            "bodies",
            "images",
            "entries",
            "jobs",
            "feedback",
            "days",
            "workout_templates",
        }
    operation = wait_operation(
        client, client.post("/api/storage/migrate", json={"path": "personal/my-health"})
    )
    assert operation["status"] == "done", operation.get("error")
    assert hub.for_user(uid).home == paths.root / "personal" / "my-health"
    assert json.loads((original / "workspace.json").read_text())["retired"]
    assert verify_store(hub.for_user(uid), uid) == before
    assert client.get(f"/api/images/{image['id']}").status_code == 200
    client.post("/api/meals", json=meal(kcal=100))
    assert client.get("/api/days/2026-10-14").json()["totals"]["kcal"] == 2100
    restored = wait_operation(client, client.post("/api/backups/restore", json={"backup_id": bid}))
    assert restored["status"] == "done", restored
    assert client.get("/api/days/2026-10-14").json()["totals"]["kcal"] == 2000
    assert original.exists() and (paths.root / "personal/my-health").exists()
    assert len(client.get("/api/storage").json()["archives"]) == 2
    assert client.get(f"/api/backups/{bid}/download").status_code == 404


def test_coaching_backup_restore_and_import_keep_reports_and_provenance(managed, monkeypatch):
    from fittrack import calculations
    from test_coaching import cardio_request, finish, seed_week, weekly_request, workout_from

    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    client.put("/api/settings", json={"api_key": "synthetic-coaching-key"})
    seed_week(hub, uid)
    monkeypatch.setattr(calculations, "today", lambda: "2026-10-22")
    cardio = finish(client, client.post("/api/jobs", json=cardio_request()))
    assert client.post("/api/workouts", json=workout_from(cardio)).status_code == 201
    weekly = finish(client, client.post("/api/jobs", json=weekly_request()))
    assert weekly["status"] == "done"
    operation = wait_operation(client, client.post("/api/backups"))
    assert operation["status"] == "done", operation
    bid = operation["result"]["backup_id"]
    source = app.state.storage_ops.backup_path(uid, bid)
    data = source.read_bytes()
    before = hub.for_user(uid).home
    restored = wait_operation(client, client.post("/api/backups/restore", json={"backup_id": bid}))
    assert restored["status"] == "done", restored
    assert before.exists()
    assert client.get("/api/weekly-review").json()["report"]["id"] == weekly["id"]
    assert not client.get("/api/weekly-review").json()["report"]["result"]["stale"]
    workout = client.get("/api/days/2026-10-15").json()["workouts"][0]
    assert workout["ai_estimate_job_id"] == cardio["id"]
    assert workout["energy"]["net_kcal"] == 375
    other = TestClient(app)
    try:
        bob = register(other, "bob")
        imported = wait_operation(
            other,
            other.post(
                "/api/backups/import", files={"file": ("health.zip", data, "application/zip")}
            ),
        )
        assert imported["status"] == "done", imported
        assert other.get(f"/api/jobs/{weekly['id']}").json()["kind"] == "weekly_review"
        assert not other.get("/api/me").json()["ai"]["api_key_set"]
        assert (
            client.get("/api/days/2026-10-15").json()["workouts"]
            == other.get("/api/days/2026-10-15").json()["workouts"]
        )
        assert hub.for_user(bob["id"]).home != hub.for_user(uid).home
    finally:
        other.close()
    # Tampered links must fail before the active workspace changes.
    malicious = paths.root / "tmp" / "broken-ai-source.zip"
    with zipfile.ZipFile(source) as original:
        manifest = json.loads(original.read("manifest.json"))
    for row in manifest["tables"]["entries"]:
        entry = json.loads(row["data"])
        if row["kind"] == "workout":
            entry["ai_estimate_job_id"] = "f" * 24
            row["data"] = json.dumps(entry)
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
    current = hub.workspace_relative(uid)
    with pytest.raises(ValueError, match="AI 来源任务缺失"):
        app.state.storage_ops.restore(uid, malicious)
    assert hub.workspace_relative(uid) == current


def test_data_failure_keeps_mapping_and_other_user_can_write(managed, monkeypatch):
    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    other = hub.register("bob", password_hash.hash("test-password-456"))["id"]
    original = hub.for_user(uid).home
    started, finish = threading.Event(), threading.Event()

    def pause(amount):
        started.set()
        finish.wait(3)
        raise ValueError("模拟核验失败")

    def move():
        with pytest.raises(ValueError, match="模拟"):
            app.state.storage_ops.migrate(uid, "personal/failed", pause)

    thread = threading.Thread(target=move)
    thread.start()
    assert started.wait(2)
    try:
        with pytest.raises(ValueError, match="迁移"):
            hub.save_profile(uid, profile())
        hub.save_profile(other, profile())
        assert hub.profile(other, "2026-10-14")
    finally:
        finish.set()
        thread.join(5)
    assert hub.for_user(uid).home == original
    assert not hub.blocked
    assert original.exists()


def test_label_records_backup_restore_and_import_preserve_calculations(managed):
    from test_diet_labels_version import label_snapshot
    from test_coaching import finish

    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    client.put("/api/settings", json={"api_key": "synthetic-label-key"})
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
                "image_id": image["id"],
                "request_key": "backup-label-task",
            },
        ),
    )
    entry = meal() | {
        "nutrition_label": label_snapshot(2),
        "image_id": image["id"],
        "source_job_id": job["id"],
    }
    saved = client.post("/api/meals", json=entry).json()
    backup = app.state.storage_ops.backup(uid)["backup_id"]
    source = app.state.storage_ops.backup_path(uid, backup)
    before = hub.for_user(uid).home
    result = wait_operation(client, client.post("/api/backups/restore", json={"backup_id": backup}))
    assert result["status"] == "done", result
    assert before.exists()
    assert (
        client.get("/api/days/2026-10-14").json()["meals"][0]["nutrition_label"]
        == saved["nutrition_label"]
    )
    other = TestClient(app)
    try:
        register(other, "bob")
        operation = wait_operation(
            other,
            other.post(
                "/api/backups/import",
                files={"file": ("label.zip", source.read_bytes(), "application/zip")},
            ),
        )
        assert operation["status"] == "done", operation
        assert other.get("/api/days/2026-10-14").json()["totals"]["kcal"] == 107.27
        assert other.get(f"/api/jobs/{job['id']}").json()["request"]["meal_mode"] == "label"
        assert not other.get("/api/me").json()["ai"]["api_key_set"]
    finally:
        other.close()


def test_backup_import_remaps_owner_and_rejects_traversal(managed):
    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    client.put("/api/profile", json=profile())
    client.post("/api/meals", json=meal())
    bid = app.state.storage_ops.backup(uid)["backup_id"]
    source = app.state.storage_ops.backup_path(uid, bid)
    data = source.read_bytes()
    bob = TestClient(app)
    try:
        other = register(bob, "bob")["id"]
        operation = wait_operation(
            bob,
            bob.post(
                "/api/backups/import", files={"file": ("archive.zip", data, "application/zip")}
            ),
        )
        assert operation["status"] == "done", operation.get("error")
        assert bob.get("/api/days/2026-10-14").json()["totals"]["kcal"] == 2000
        assert all(
            row["user_id"] == other
            for row in hub.for_user(other).rows("SELECT user_id FROM entries")
        )
    finally:
        bob.close()
    malicious = paths.root / "tmp" / "malicious.zip"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("manifest.json", original.read("manifest.json"))
        archive.writestr("../outside.txt", "bad")
    before = hub.workspace_relative(uid)
    with pytest.raises(ValueError, match="越界"):
        app.state.storage_ops.restore(uid, malicious)
    assert hub.workspace_relative(uid) == before
    assert not (paths.root / "outside.txt").exists()


def test_operation_recovery_and_pending_ai_block_moves(managed):
    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    store = hub.for_user(uid)
    request = {"kind": "feedback", "date": "2026-10-14", "request_key": "pending-test"}
    store.create_job(uid, request)
    assert client.post("/api/storage/migrate", json={"path": "personal/new"}).status_code == 400
    from fittrack.paths import write_json

    ident = "a" * 24
    write_json(
        paths.root / "runtime/operations" / f"{ident}.json",
        {"id": ident, "user_id": uid, "status": "running", "kind": "backup"},
    )
    recovered = StorageOperations(hub)
    try:
        assert recovered.get(uid, ident)["status"] == "interrupted"
    finally:
        recovered.shutdown()


def test_root_move_verifies_copies_clears_sessions_and_retains_source(tmp_path):
    source = RuntimePaths.initialize(tmp_path / "source")
    hub = WorkspaceHub(source)
    vault = CredentialStore(hub.control, source)
    uid = hub.register("alice", password_hash.hash("test-password-123"))["id"]
    hub.session(uid)
    hub.save_profile(uid, profile())
    vault.save_for(uid, "", {"api_key": "portable-ciphertext"})
    (source.root / "logs" / "example.log").write_text("no secrets")
    hub.close()
    bound = []
    moved = relocate_root(source.root, tmp_path / "destination", bound.append)
    assert bound == [moved.root]
    assert source.root.exists()
    assert json.loads((source.root / "fittrack-root.json").read_text())["moved_to"] == str(
        moved.root
    )
    with pytest.raises(ValueError, match="已迁移"):
        RuntimePaths.initialize(source.root)
    new = WorkspaceHub(moved)
    try:
        assert new.profile(uid, "2026-10-14")["initial_weight_kg"] == 75
        assert not new.control.rows("SELECT * FROM sessions")
        assert (
            CredentialStore(new.control, moved).snapshot_for(uid)["api_key"]
            == "portable-ciphertext"
        )
    finally:
        new.close()


def test_legacy_upgrade_keeps_auth_records_and_moves_only_original_admin_key(tmp_path):
    old = Store(tmp_path / "legacy")
    uid = old.register("alice", password_hash.hash("test-password-123"))["id"]
    other = old.register("bob", password_hash.hash("test-password-456"))["id"]
    old.save_profile(uid, profile())
    old.save_entry(uid, "meal", meal())
    original_hash = old.rows("SELECT password_hash FROM users WHERE id=?", (uid,))[0][
        "password_hash"
    ]
    old.session(uid)
    old.close()
    env = tmp_path / "legacy.env"
    env.write_text(
        "FITTRACK_AI_API_KEY=synthetic-legacy-key\nFITTRACK_AI_COACH_MODEL=deepseek-flash\n"
    )
    paths = RuntimePaths.initialize(tmp_path / "new-root")
    hub = WorkspaceHub(paths)
    vault = CredentialStore(hub.control, paths)
    try:
        import_legacy(hub, vault, tmp_path / "legacy", env)
        assert (
            hub.control.rows("SELECT password_hash FROM users WHERE id=?", (uid,))[0][
                "password_hash"
            ]
            == original_hash
        )
        assert not hub.control.rows("SELECT * FROM sessions")
        assert hub.summary(uid, "2026-10-14")["totals"]["kcal"] == 2000
        assert vault.snapshot_for(uid)["api_key"] == "synthetic-legacy-key"
        assert not vault.snapshot_for(other)["api_key"]
        assert "API_KEY" not in env.read_text()
        assert (paths.root / "backups/legacy-v1/original.sqlite3").is_file()
        assert (tmp_path / "legacy/fittrack.sqlite3").is_file()
        import_legacy(hub, vault, tmp_path / "legacy", env)
        assert len(hub.control.rows("SELECT * FROM users")) == 2
    finally:
        hub.close()


def test_server_guards_native_operations_and_credentials(managed):
    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    config = RuntimeConfig("server", "https://fitness.example")
    server_vault = CredentialStore(hub.control, paths, "server", config.providers)
    server = create_app(hub, server_vault, ai=FakeAI(), runtime_config=config)
    with TestClient(server, base_url="https://fitness.example") as browser:
        assert (
            browser.post(
                "/api/auth/login", json={"username": "alice", "password": "test-password-123"}
            ).status_code
            == 200
        )
        assert (
            "Secure"
            in browser.post(
                "/api/auth/login", json={"username": "alice", "password": "test-password-123"}
            ).headers["set-cookie"]
        )
        assert not browser.get("/api/me").json()["runtime"]["choose_directory"]
        for endpoint, data in (
            ("/api/storage/pick-directory", {}),
            ("/api/storage/migrate", {"path": "records/test"}),
            ("/api/storage/open", {"path": "workspace"}),
            ("/api/local/stop", {}),
            ("/api/local/root-migration", {"path": str(paths.root.parent / "move")}),
        ):
            assert browser.post(endpoint, json=data).status_code == 404
        assert browser.get("/_local/health").status_code == 404
        assert (
            browser.put(
                "/api/settings", json={"api_key": "own-key", "base_url": "http://127.0.0.1:1"}
            ).status_code
            == 400
        )
        assert (
            browser.put(
                "/api/settings", json={"api_key": "own-key", "base_url": "https://api.deepseek.com"}
            ).status_code
            == 200
        )
        assert browser.get("/api/me", headers={"host": "evil.example"}).status_code == 403
        assert (
            browser.put(
                "/api/profile", json=profile(), headers={"origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert str(paths.root) not in browser.get("/api/storage").text
        assert server_vault.snapshot_for(uid)["api_key"] == "own-key"


def test_server_revalidates_locally_saved_provider(managed):
    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    client.put("/api/settings", json={"api_key": "local-only", "base_url": "http://127.0.0.1:1234"})
    server_vault = CredentialStore(hub.control, paths, "server")
    with pytest.raises(ValueError, match="HTTPS"):
        server_vault.snapshot_for(uid)
    assert not server_vault.public_for(uid)["api_key_set"]


def test_startup_cancel_makes_no_root(tmp_path, monkeypatch):
    import os
    import sys
    from fittrack import cli, desktop

    if os.name != "nt":
        pytest.skip("Native Windows first-launch picker")

    monkeypatch.setattr(sys, "argv", ["fittrack", "--background"])
    monkeypatch.setattr(desktop, "pick_directory", lambda: None)
    assert cli.main() == 0
    assert list(tmp_path.iterdir()) == []


def test_root_relocation_failure_retains_original(tmp_path):
    source = RuntimePaths.initialize(tmp_path / "original")
    hub = WorkspaceHub(source)
    CredentialStore(hub.control, source)
    hub.register("alice", password_hash.hash("test-password-123"))
    hub.close()

    def failed_binding(root):
        raise OSError("synthetic shortcut failure")

    with pytest.raises(OSError):
        relocate_root(source.root, tmp_path / "failed-target", failed_binding)
    assert "moved_to" not in json.loads((source.root / "fittrack-root.json").read_text())
    assert RuntimePaths.initialize(source.root).identity == source.identity


def test_restartable_legacy_import_retains_source_on_copy_error(tmp_path, monkeypatch):
    import fittrack.upgrade as upgrade

    old = Store(tmp_path / "legacy")
    uid = old.register("alice", password_hash.hash("test-password-123"))["id"]
    old.save_profile(uid, profile())
    old.close()
    paths = RuntimePaths.initialize(tmp_path / "new-root")
    hub = WorkspaceHub(paths)
    vault = CredentialStore(hub.control, paths)
    original_import = upgrade.import_rows

    def fail_once(*args):
        raise OSError("synthetic full disk")

    monkeypatch.setattr(upgrade, "import_rows", fail_once)
    try:
        with pytest.raises(OSError):
            import_legacy(hub, vault, tmp_path / "legacy", None)
        assert not hub.control.metadata("legacy_complete")
        assert hub.control.metadata("legacy_in_progress")
        monkeypatch.setattr(upgrade, "import_rows", original_import)
        import_legacy(hub, vault, tmp_path / "legacy", None)
        assert hub.control.metadata("legacy_complete")
        assert hub.profile(uid, "2026-10-14")["height_cm"] == 175
        assert (tmp_path / "legacy/fittrack.sqlite3").exists()
    finally:
        hub.close()


def test_windows_junction_cannot_escape_root(tmp_path):
    import os
    import subprocess

    if os.name != "nt":
        pytest.skip("Windows junction-specific check")
    paths = RuntimePaths.initialize(tmp_path / "root")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = paths.root / "records/escape"
    # Native reparse-point creation, no shell deletion or recursive move.
    response = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert response.returncode == 0
    with pytest.raises(ValueError):
        paths.workspace("records/escape/health")
    with pytest.raises(ValueError, match="链接|联接"):
        RuntimePaths.initialize(paths.root)
    # Remove just the verified junction itself; never walk its target.
    assert link.lstat().st_file_attributes & 0x400 and link.parent.resolve().is_relative_to(
        paths.root
    )
    link.rmdir()
    assert outside.exists()


def test_runtime_writes_stay_in_selected_root(managed):
    import os
    import sys

    client, app, hub, vault, paths = managed
    register(client)
    writes = []
    auditing = True

    def audit(event, args):
        if not auditing:
            return
        if event == "open":
            location, mode, flags = args
            if isinstance(location, (str, bytes, os.PathLike)) and flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT
            ):
                writes.append(Path(os.fsdecode(location)).resolve())
        elif event == "os.mkdir":
            writes.append(Path(os.fsdecode(args[0])).resolve())
        elif event == "sqlite3.connect" and args[0] != ":memory:":
            writes.append(Path(args[0]).resolve())

    sys.addaudithook(audit)
    try:
        assert (
            client.put("/api/settings", json={"api_key": "audit-synthetic-key"}).status_code == 200
        )
        assert client.put("/api/profile", json=profile()).status_code == 200
        assert (
            client.post(
                "/api/uploads", files={"file": ("test.png", picture(), "image/png")}
            ).status_code
            == 201
        )
        assert wait_operation(client, client.post("/api/backups"))["status"] == "done"
        assert (
            wait_operation(
                client, client.post("/api/storage/migrate", json={"path": "personal/audited"})
            )["status"]
            == "done"
        )
    finally:
        auditing = False
    assert writes
    assert all(path.is_relative_to(paths.root) for path in writes), [
        str(p) for p in writes if not p.is_relative_to(paths.root)
    ]


def test_progress_file_survives_concurrent_windows_reader(tmp_path):
    from fittrack.paths import read_json, write_json

    path = tmp_path / "operation.json"
    write_json(path, {"status": "running"})
    reader = path.open("r", encoding="utf-8")
    errors = []

    def update():
        try:
            write_json(path, {"status": "done"})
        except OSError as exc:
            errors.append(type(exc).__name__)

    worker = threading.Thread(target=update)
    worker.start()
    time.sleep(0.05)
    reader.close()
    worker.join(3)
    assert not worker.is_alive()
    assert not errors
    assert read_json(path)["status"] == "done"


@pytest.mark.parametrize("mode", ["photo", "label"])
def test_deleted_analysis_backup_restores_meal_without_dangling_source(managed, mode):
    import hashlib

    from test_delete_meal_jobs import analysis
    from test_diet_labels_version import label_snapshot

    client, app, hub, vault, paths = managed
    uid = register(client)["id"]
    job, image = analysis(hub, uid, mode=mode)
    payload = meal() | {"source_job_id": job["id"], "image_id": image["id"]}
    if mode == "label":
        payload["nutrition_label"] = label_snapshot()
    assert client.post("/api/meals", json=payload).status_code == 201
    old_backup = wait_operation(client, client.post("/api/backups"))["result"]["backup_id"]
    old_path = paths.root / "backups" / uid / f"{old_backup}.zip"
    old_digest = hashlib.sha256(old_path.read_bytes()).hexdigest()
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    backup = wait_operation(client, client.post("/api/backups"))["result"]["backup_id"]
    result = wait_operation(client, client.post("/api/backups/restore", json={"backup_id": backup}))
    assert result["status"] == "done", result
    assert hashlib.sha256(old_path.read_bytes()).hexdigest() == old_digest
    day = client.get("/api/days/2026-10-14").json()
    assert len(day["meals"]) == 1 and day["meals"][0]["source_job_id"] is None
    assert not day["jobs"]
    assert day["totals"]["kcal"] == (53.63 if mode == "label" else 2000)
    assert client.get(f"/api/images/{image['id']}").content == picture()
    assert verify_store(hub.for_user(uid), uid)["jobs"] == 0
    assert client.put(
        f"/api/meals/{day['meals'][0]['id']}", json=payload | {"source_job_id": None}
    ).status_code == 200
