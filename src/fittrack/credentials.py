"""Per-account encrypted credentials. Session-only secrets never enter SQLite."""

import hashlib
import json
import threading
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken

from fittrack.paths import private
from fittrack.store import encode

DEFAULTS = {
    "base_url": "https://api.deepseek.com",
    "vision_model": "deepseek-flash",
    "coach_model": "deepseek-flash",
    "remember": True,
}


class CredentialStore:
    def __init__(self, control, paths, mode="local", providers=None):
        self.control, self.paths, self.mode = control, paths, mode
        self.providers = set(providers or ["https://api.deepseek.com"])
        self.lock = threading.RLock()
        self._memory = {}
        self.keyfile = paths.root / "secrets" / "master.key"
        if not self.keyfile.exists() and not control.rows(
            "SELECT 1 FROM ai WHERE ciphertext IS NOT NULL LIMIT 1"
        ):
            with self.keyfile.open("xb") as output:
                output.write(Fernet.generate_key())
            private(self.keyfile)

    @staticmethod
    def session_id(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def _fernet(self):
        try:
            return Fernet(self.keyfile.read_bytes())
        except (OSError, ValueError) as exc:
            raise ValueError("主密钥不可用，请恢复根目录备份或使用本次登录临时 Key") from exc

    def _row(self, uid):
        rows = self.control.rows("SELECT data,ciphertext FROM ai WHERE user_id=?", (uid,))
        return rows[0] if rows else {"data": encode(DEFAULTS), "ciphertext": None}

    def snapshot_for(self, uid, token=""):
        self.control.user(uid)
        with self.lock:
            row = self._row(uid)
            data = DEFAULTS | json.loads(row["data"])
            data["base_url"] = self.validate_url(data["base_url"])
            memory_id = (uid, self.session_id(token))
            key = self._memory.get(memory_id, "")
            if key:
                try:
                    if self.control.session_user(token)["id"] != uid:
                        raise KeyError("会话不匹配")
                except KeyError:
                    self._memory.pop(memory_id, None)
                    key = ""
            if not key and row["ciphertext"]:
                try:
                    key = self._fernet().decrypt(row["ciphertext"].encode()).decode()
                except InvalidToken as exc:
                    raise ValueError("保存的 Key 无法解密，请恢复主密钥或重新配置") from exc
            return data | {"api_key": key}

    def public_for(self, uid, token=""):
        with self.lock:
            row = self._row(uid)
            data = DEFAULTS | json.loads(row["data"])
            error = ""
            try:
                configured = bool(self.snapshot_for(uid, token)["api_key"])
            except ValueError as exc:
                configured, error = False, str(exc)
            return data | {
                "api_key_set": configured,
                "environment_override": False,
                "credential_scope": "account"
                if row["ciphertext"]
                else "session"
                if configured
                else "none",
                "credential_error": error,
            }

    def validate_url(self, value):
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in value)
        ):
            raise ValueError("服务地址必须是有效的 HTTP(S) 地址，不能包含密码或查询参数")
        normalized = value.rstrip("/")
        if self.mode == "server" and (parsed.scheme != "https" or normalized not in self.providers):
            raise ValueError("服务器模式仅允许部署管理员配置的 HTTPS AI 服务地址")
        return normalized

    def save_for(self, uid, token, values):
        self.control.user(uid)
        with self.lock:
            row = self._row(uid)
            data = DEFAULTS | json.loads(row["data"])
            for name in DEFAULTS:
                if name in values and values[name] is not None:
                    data[name] = values[name]
            data["base_url"] = self.validate_url(data["base_url"])
            for name in ("vision_model", "coach_model"):
                if not data[name].strip() or any(c in data[name] for c in "\r\n"):
                    raise ValueError("模型名称不能为空或包含换行")
            supplied = values.get("api_key")
            if supplied is not None and any(c.isspace() for c in supplied):
                raise ValueError("API Key 不能包含空白字符")
            if supplied:
                key = supplied
            else:
                try:
                    key = self.snapshot_for(uid, token)["api_key"]
                except ValueError:
                    raise ValueError("请重新输入 Key，空白输入不会覆盖无法解密的旧凭据") from None
            ciphertext = (
                self._fernet().encrypt(key.encode()).decode() if key and data["remember"] else None
            )
            if key and not data["remember"]:
                if self.control.session_user(token)["id"] != uid:
                    raise ValueError("临时 Key 必须绑定当前有效登录会话")
            with self.control.lock:
                self.control.db.execute(
                    "INSERT INTO ai VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,ciphertext=excluded.ciphertext",
                    (uid, encode(data), ciphertext),
                )
            if data["remember"]:
                self._memory = {k: v for k, v in self._memory.items() if k[0] != uid}
            elif key:
                self._memory = {k: v for k, v in self._memory.items() if k[0] != uid}
                self._memory[(uid, self.session_id(token))] = key
            return self.public_for(uid, token)

    def clear_for(self, uid):
        with self.lock, self.control.lock:
            self.control.db.execute("UPDATE ai SET ciphertext=NULL WHERE user_id=?", (uid,))
            self._memory = {k: v for k, v in self._memory.items() if k[0] != uid}

    def logout(self, uid, token):
        with self.lock:
            self._memory.pop((uid, self.session_id(token)), None)

    def purge_expired(self):
        import time

        valid = {
            row["token_hash"]
            for row in self.control.rows(
                "SELECT token_hash FROM sessions WHERE expires_at>?", (time.time(),)
            )
        }
        with self.lock:
            self._memory = {k: v for k, v in self._memory.items() if k[1] in valid}

    def test_for(self, uid, token):
        config = self.snapshot_for(uid, token)
        if not config["api_key"]:
            raise ValueError("请先保存你自己的 API Key")
        try:
            with requests.get(
                config["base_url"] + "/models",
                headers={"Authorization": "Bearer " + config["api_key"]},
                timeout=(10, 15),
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise ValueError(f"连接测试失败（HTTP {response.status_code}），原配置已保留")
                data = response.json()
                models = [item.get("id") for item in data.get("data", [])]
                return {
                    "ok": True,
                    "models_available": all(
                        config[key] in models for key in ("vision_model", "coach_model")
                    ),
                    "message": "连接及鉴权正常；模型列表检查不会验证识图或生成效果",
                }
        except (requests.RequestException, json.JSONDecodeError, AttributeError, TypeError) as exc:
            raise ValueError("无法连接 AI 服务，配置已保留，可稍后手动测试") from exc
