"""Local configuration and single-instance lock; inspired by BrushGraft (MIT)."""

import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def values(self) -> dict[str, str]:
        with self._lock:
            result = {}
            if self.path.exists():
                for line in self.path.read_text(encoding="utf-8-sig").splitlines():
                    if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        result[key.strip()] = value.strip().strip("\"'")
            return result

    def get(self, name: str, default: str = "") -> str:
        key = "FITTRACK_AI_" + name
        return os.environ.get(key, self.values().get(key, default)).strip()

    def snapshot(self) -> dict[str, str]:
        return {
            "api_key": self.get("API_KEY"),
            "base_url": self.get("BASE_URL", "https://api.deepseek.com"),
            "vision_model": self.get("VISION_MODEL", "deepseek-flash"),
            "coach_model": self.get("COACH_MODEL", "deepseek-flash"),
        }

    def public(self) -> dict:
        values = self.snapshot()
        return {key: value for key, value in values.items() if key != "api_key"} | {
            "api_key_set": bool(values["api_key"]),
            "environment_override": any(key.startswith("FITTRACK_AI_") for key in os.environ),
        }

    def save(self, values: dict) -> dict:
        with self._lock:
            existing = self.values()
            for key, value in values.items():
                if value is None:
                    continue
                if "\n" in value or "\r" in value:
                    raise ValueError("配置值不能包含换行")
                if key == "base_url":
                    parsed = urlparse(value)
                    if (
                        parsed.scheme not in {"http", "https"}
                        or any(character.isspace() for character in value)
                        or not parsed.hostname
                        or parsed.username
                        or parsed.password
                        or parsed.query
                        or parsed.fragment
                    ):
                        raise ValueError("服务地址必须是有效的 HTTP(S) 地址")
                    value = value.rstrip("/")
                existing["FITTRACK_AI_" + key.upper()] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Rewrite in place to retain the restrictive Windows DACL.
            if self.path.exists():
                self.path.write_text(
                    "".join(f"{k}={v}\n" for k, v in existing.items()), encoding="utf-8"
                )
            else:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    file.write("".join(f"{k}={v}\n" for k, v in existing.items()))
            return self.public()


def lock_home(home: Path, *, create=True):
    if create:
        home.mkdir(parents=True, exist_ok=True)
    elif not (home / ".lock").exists():
        return None
    handle = open(home / ".lock", "a+b" if create else "r+b")
    if create and (home / ".lock").stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError("数据目录正在使用，请先关闭另一个 FitTrack") from exc
    return handle


def atomic_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        if not path.exists():
            try:
                os.replace(temporary, path)
            except OSError:
                if not path.exists():
                    raise
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
