"""Explicit runtime root. No AppData, registry, cwd or system-temp fallback."""

import json
import os
import secrets
import sys
import tempfile
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path


AREAS = ("control", "secrets", "records", "logs", "tmp", "caches", "backups", "runtime")
_JSON_LOCK = threading.RLock()


def read_json(path: Path):
    with _JSON_LOCK:
        return json.loads(path.read_text(encoding="utf-8"))


def reject_links(folder: Path):
    """Never follow symlinks or Windows junctions when managing application data."""
    for entry in os.scandir(folder):
        path = Path(entry.path)
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        if entry.is_symlink() or attributes & 0x400:
            raise ValueError("数据目录内不能包含符号链接或目录联接")
        if entry.is_dir(follow_symlinks=False):
            reject_links(path)


def private(path: Path):
    if os.name == "nt":
        import subprocess
        import ctypes

        size = ctypes.c_ulong(256)
        name = ctypes.create_unicode_buffer(256)
        if not ctypes.windll.secur32.GetUserNameExW(2, name, ctypes.byref(size)):
            raise OSError("无法确认当前 Windows 用户，未保存敏感文件")
        from fittrack.distribution import external_program

        with external_program() as env:
            result = subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{name.value}:(OI)(CI)F" if path.is_dir() else f"{name.value}:F",
                    "SYSTEM:(OI)(CI)F" if path.is_dir() else "SYSTEM:F",
                ],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env,
            )
        if result.returncode:
            raise OSError("无法限制数据目录访问权限")
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def write_json(path: Path, value):
    with _JSON_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        # Windows readers in another process can briefly deny delete-sharing.
        for attempt in range(30):
            try:
                os.replace(temporary, path)
                return
            except OSError as exc:
                if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 29:
                    raise
                time.sleep(0.01)


def within(root: Path, candidate: Path) -> Path:
    base, resolved = root.resolve(), candidate.resolve()
    if resolved == base or not resolved.is_relative_to(base):
        raise ValueError("位置必须是数据根目录内的专用子目录")
    return resolved


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @classmethod
    def initialize(cls, location: Path):
        if not location.is_absolute():
            raise ValueError("请明确指定绝对数据根目录")
        root = location.resolve()
        root.mkdir(parents=True, exist_ok=True)
        marker = root / "fittrack-root.json"
        if not marker.exists():
            if any(root.iterdir()):
                raise ValueError("请选择空文件夹或已有有效 FitTrack 数据根目录")
            private(root)
            write_json(
                marker, {"format": "fittrack-root", "version": 2, "id": secrets.token_hex(16)}
            )
            (root / ".gitignore").write_text("*\n", encoding="utf-8")
        info = json.loads(marker.read_text(encoding="utf-8"))
        if info.get("format") != "fittrack-root" or info.get("version") != 2:
            raise ValueError("数据根目录格式不兼容")
        if info.get("incomplete"):
            raise ValueError("此目录的迁移尚未完成，请使用原目录启动入口")
        if info.get("moved_to"):
            raise ValueError("此目录已迁移，请使用新目录绑定的启动入口：" + info["moved_to"])
        reject_links(root)
        if shutil.disk_usage(root).free < 64 * 1024 * 1024:
            raise ValueError("数据盘可用空间不足 64 MiB，请释放空间后重试")
        for area in AREAS:
            within(root, root / area).mkdir(exist_ok=True)
        # All subsequent tempfile users use this exact folder; no fallback probing.
        probe = root / "tmp" / ("probe-" + secrets.token_hex(8))
        with probe.open("xb") as output:
            output.write(b"ok")
        probe.unlink()
        return cls(root)

    def configure_process(self):
        sys.dont_write_bytecode = True
        for key in ("TMP", "TEMP", "TMPDIR", "SQLITE_TMPDIR"):
            os.environ[key] = str(self.root / "tmp")
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        shell_cache = self.root / "caches" / "powershell"
        shell_cache.mkdir(parents=True, exist_ok=True)
        os.environ["PSModuleAnalysisCachePath"] = str(shell_cache / "ModuleAnalysisCache")
        tempfile.tempdir = str(self.root / "tmp")

    @property
    def identity(self):
        return json.loads((self.root / "fittrack-root.json").read_text(encoding="utf-8"))["id"]

    def child(self, relative: str):
        return within(self.root, self.root / relative)

    def workspace(self, relative: str):
        path = self.child(relative)
        parts = path.relative_to(self.root).parts
        if parts[0] in set(AREAS) - {"records"} or parts == ("records",):
            raise ValueError("不能使用应用管理、密钥、日志或备份目录保存健康记录")
        return path
