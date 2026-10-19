"""Restart-safe v1 import. All new copies and staging remain in the chosen root."""

import shutil
from pathlib import Path

from fittrack.config import Settings, lock_home
from fittrack.control import HEALTH_TABLES
from fittrack.storage_ops import import_rows, verify_store
from fittrack.store import Store


def import_legacy(hub, credentials, source: Path, env_file: Path | None):
    source = source.resolve()
    if hub.control.metadata("legacy_complete"):
        return
    if not (source / "fittrack.sqlite3").is_file():
        raise ValueError("旧版数据库不存在")
    if hub.control.rows("SELECT id FROM users") and not hub.control.metadata("legacy_in_progress"):
        raise ValueError("新根目录已有账号，不能自动覆盖导入旧版；请使用空根目录")
    hub.control.set_metadata("legacy_source", str(source))
    hub.control.set_metadata("legacy_env", str(env_file) if env_file else None)
    # Reuse an existing v1 lock without creating a new runtime file in the source.
    handle = lock_home(source, create=False)
    staging = hub.paths.root / "tmp" / "legacy-import"
    staging.mkdir(exist_ok=True)
    legacy = None
    try:
        hub.control.set_metadata("legacy_in_progress", True)
        # Copy main/WAL/SHM first; any SQLite recovery then writes only in R/tmp.
        for suffix in ("", "-wal", "-shm"):
            old = source / ("fittrack.sqlite3" + suffix)
            (staging / old.name).unlink(missing_ok=True)
            if old.exists():
                shutil.copyfile(old, staging / old.name)
        legacy = Store(staging)
        if legacy.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("旧版数据库完整性检查失败")
        backup = hub.paths.root / "backups" / "legacy-v1"
        backup.mkdir(exist_ok=True)
        import sqlite3

        with sqlite3.connect(backup / "original.sqlite3") as output:
            legacy.db.backup(output)
        for user in legacy.rows("SELECT * FROM users"):
            with hub.control.lock:
                hub.control.db.execute(
                    "INSERT OR IGNORE INTO users VALUES(?,?,?,?,?)",
                    tuple(
                        user[k]
                        for k in ("id", "username", "password_hash", "is_admin", "created_at")
                    ),
                )
            uid = user["id"]
            store = hub.for_user(uid)
            tables = {
                table: legacy.rows(f"SELECT * FROM {table} WHERE user_id=?", (uid,))
                for table in HEALTH_TABLES
            }
            for image in tables["images"]:
                name = f"{image['sha']}.{image['ext']}"
                shutil.copyfile(source / "images" / name, store.images / name)
            import_rows(store, uid, tables)
            verify_store(store, uid)
        admins = legacy.rows("SELECT id FROM users WHERE is_admin=1")
        if env_file and env_file.is_file():
            values = Settings(env_file).values()  # explicit file only, no global env fallback
            key = values.get("FITTRACK_AI_API_KEY", "")
            if key and len(admins) == 1:
                credentials.save_for(
                    admins[0]["id"],
                    "",
                    {
                        "api_key": key,
                        "remember": True,
                        "base_url": values.get("FITTRACK_AI_BASE_URL", "https://api.deepseek.com"),
                        "vision_model": values.get("FITTRACK_AI_VISION_MODEL", "deepseek-flash"),
                        "coach_model": values.get("FITTRACK_AI_COACH_MODEL", "deepseek-flash"),
                    },
                )
                assert credentials.snapshot_for(admins[0]["id"])["api_key"] == key
                # Preserve original ACL while removing only the migrated plaintext.
                lines = env_file.read_text(encoding="utf-8-sig").splitlines()
                env_file.write_text(
                    "\n".join(
                        line
                        for line in lines
                        if line.partition("=")[0].strip() != "FITTRACK_AI_API_KEY"
                    )
                    + "\n",
                    encoding="utf-8",
                )
        hub.control.set_metadata("legacy_paths", [str(source)])
        hub.control.set_metadata("legacy_complete", True)
        hub.control.set_metadata("legacy_in_progress", False)
    finally:
        if legacy:
            legacy.close()
        if handle:
            handle.close()
        # Only our fixed staging folder, verified to be inside the selected root.
        if staging.resolve().is_relative_to(hub.paths.root / "tmp"):
            shutil.rmtree(staging)
