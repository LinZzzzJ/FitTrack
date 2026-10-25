"""Scoped device sessions and bounded pairing attempts; no health data here."""

import hashlib
import secrets
import threading
import time
from collections import OrderedDict

from fastapi import HTTPException

NATIVE_ORIGINS = frozenset({"capacitor://localhost", "http://localhost", "https://localhost"})


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def request_token(request):
    authorization = request.headers.get("authorization", "")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 200:
            raise HTTPException(401, "设备令牌无效")
        store = getattr(request.app.state.store, "control", request.app.state.store)
        if not store.rows("SELECT 1 FROM mobile_devices WHERE token_hash=?", (digest(token),)):
            raise HTTPException(401, "设备已撤销，请重新配对")
        return token
    return request.cookies.get("fittrack_session", "")


class PairingLimiter:
    def __init__(self, message="配对尝试过于频繁，请稍后再试"):
        self.message = message
        self.lock = threading.Lock()
        self.attempts = OrderedDict()
        self.global_attempts = []

    def check(self, address):
        now = time.monotonic()
        with self.lock:
            self.global_attempts = [x for x in self.global_attempts if x > now - 60]
            recent = [x for x in self.attempts.pop(address, []) if x > now - 60]
            if len(recent) >= 10 or len(self.global_attempts) >= 200:
                raise HTTPException(429, self.message)
            recent.append(now)
            self.attempts[address] = recent
            self.global_attempts.append(now)
            while len(self.attempts) > 4096:
                self.attempts.popitem(last=False)


def device_schema():
    return """
CREATE TABLE IF NOT EXISTS mobile_pairings(code_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires_at REAL NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mobile_devices(token_hash TEXT PRIMARY KEY REFERENCES sessions(token_hash) ON DELETE CASCADE,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,name TEXT NOT NULL,created_at REAL NOT NULL);
"""


def create_pair(control, uid):
    now = time.time()
    with control.lock:
        control.db.execute(
            "DELETE FROM mobile_pairings WHERE expires_at<=? OR user_id=?", (now, uid)
        )
        if control.db.execute("SELECT COUNT(*) FROM mobile_pairings").fetchone()[0] >= 1000:
            raise HTTPException(429, "当前配对请求过多，请稍后再试")
        for _ in range(5):
            code = f"{secrets.randbelow(100_000_000):08d}"
            if not control.rows("SELECT 1 FROM mobile_pairings WHERE code_hash=?", (digest(code),)):
                control.db.execute(
                    "INSERT INTO mobile_pairings VALUES(?,?,?,?)",
                    (digest(code), uid, now + 300, now),
                )
                return {"code": code, "expires_in": 300}
        raise HTTPException(503, "配对暂不可用，请重试")


def redeem_pair(control, code):
    with control.lock:
        control.db.execute("BEGIN IMMEDIATE")
        try:
            row = control.db.execute(
                "SELECT user_id FROM mobile_pairings WHERE code_hash=? AND expires_at>?",
                (digest(code), time.time()),
            ).fetchone()
            if not row:
                raise HTTPException(401, "配对码无效或已过期")
            uid = row[0]
            token = control.session(uid)
            control.db.execute(
                "INSERT INTO mobile_devices VALUES(?,?,?,?)",
                (digest(token), uid, "Android", time.time()),
            )
            control.db.execute("DELETE FROM mobile_pairings WHERE code_hash=?", (digest(code),))
            control.db.execute("COMMIT")
        except Exception:
            control.db.execute("ROLLBACK")
            raise
    return {"token": token, "expires_in": 14 * 86400, "user": control.user(uid)}
