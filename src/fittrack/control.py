"""Account control DB plus user-bound dispatch to separate health databases."""

import json
import sqlite3
import threading
from contextlib import contextmanager

from fittrack.paths import write_json
from fittrack.mobile_auth import device_schema
from fittrack.store import Store, encode

CONTROL = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,is_admin INTEGER NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS workspaces(user_id TEXT PRIMARY KEY REFERENCES users(id),path TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS ai(user_id TEXT PRIMARY KEY REFERENCES users(id),data TEXT NOT NULL,ciphertext TEXT);
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""
HEALTH_TABLES = (
    "profiles",
    "bodies",
    "images",
    "entries",
    "jobs",
    "feedback",
    "days",
    "workout_templates",
)


class ControlStore(Store):
    def __init__(self, paths):
        self.home = paths.root / "control"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            self.home / "accounts.sqlite3",
            check_same_thread=False,
            isolation_level=None,
            timeout=10,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA temp_store=MEMORY")
        self.db.executescript(CONTROL + device_schema())

    def metadata(self, key, default=None):
        rows = self.rows("SELECT value FROM metadata WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_metadata(self, key, value):
        with self.lock:
            self.db.execute(
                "INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, encode(value)),
            )


class WorkspaceHub:
    def __init__(self, paths):
        self.paths, self.home = paths, paths.root
        self.control = ControlStore(paths)
        self.lock = threading.RLock()
        self._stores = {}
        self.blocked = set()
        self.frozen = False

    @property
    def db(self):
        return self.control.db

    def rows(self, sql, args=()):
        # Routes that inspect health rows pass user_id first; auth stays in control.
        if any(f"FROM {table}" in sql for table in HEALTH_TABLES):
            if not args:
                raise ValueError("健康数据查询必须指定账号")
            with self.lock:
                return self.for_user(args[0]).rows(sql, args)
        return self.control.rows(sql, args)

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        if not rows:
            raise KeyError("记录不存在")
        return rows[0]

    def register(self, username, password_hash):
        with self.lock:
            if self.frozen:
                raise ValueError("服务正在迁移，暂不可注册")
            user = self.control.register(username, password_hash)
            self.for_user(user["id"])
            return user

    def user(self, uid):
        return self.control.user(uid)

    def session(self, uid):
        return self.control.session(uid)

    def session_user(self, token):
        return self.control.session_user(token)

    def logout(self, token):
        return self.control.logout(token)

    def workspace_relative(self, uid):
        self.control.user(uid)
        rows = self.control.rows("SELECT path FROM workspaces WHERE user_id=?", (uid,))
        if rows:
            return rows[0]["path"]
        relative = f"records/{uid}"
        with self.control.lock:
            self.control.db.execute("INSERT OR IGNORE INTO workspaces VALUES(?,?)", (uid, relative))
        return relative

    def for_user(self, uid):
        with self.lock:
            if uid not in self._stores:
                relative = self.workspace_relative(uid)
                location = self.paths.workspace(relative)
                if (location / "workspace.json").exists():
                    info = json.loads((location / "workspace.json").read_text(encoding="utf-8"))
                    if info.get("owner") != uid or info.get("retired") or info.get("incomplete"):
                        raise ValueError("工作区归属不符或已归档")
                store = Store(location, owner_id=uid)
                write_json(
                    location / "workspace.json", {"format": "fittrack-workspace", "owner": uid}
                )
                self._stores[uid] = store
            return self._stores[uid]

    def assert_writable(self, uid):
        if self.frozen or uid in self.blocked:
            raise ValueError("数据正在迁移或备份，请稍后再保存")

    def pending(self, uid=None):
        ids = [uid] if uid else [row["id"] for row in self.control.rows("SELECT id FROM users")]
        return sum(
            self.for_user(item).rows(
                "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','running')"
            )[0]["n"]
            for item in ids
        )

    def recover_jobs(self):
        for row in self.control.rows("SELECT id FROM users"):
            self.for_user(row["id"]).recover_jobs()

    def close(self):
        with self.lock:
            for store in self._stores.values():
                store.close()
            self._stores.clear()
            self.control.close()

    def __getattr__(self, name):
        if not hasattr(Store, name):
            raise AttributeError(name)

        def call(uid, *args, **kwargs):
            with self.lock:
                if name.startswith(("save_", "delete_", "put_", "create_", "complete_")):
                    self.assert_writable(uid)
                return getattr(self.for_user(uid), name)(uid, *args, **kwargs)

        return call

    @contextmanager
    def maintenance(self, uid):
        with self.lock:
            self.assert_writable(uid)
            if self.pending(uid):
                raise ValueError("请等待当前 AI 任务结束后再操作数据")
            self.blocked.add(uid)
            source = self.for_user(uid)
        try:
            yield source
        finally:
            with self.lock:
                self.blocked.discard(uid)
