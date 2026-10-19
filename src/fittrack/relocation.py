"""Offline whole-root relocation after all application databases have closed."""

import json
import hashlib
import shutil
from pathlib import Path

from fittrack.control import WorkspaceHub
from fittrack.credentials import CredentialStore
from fittrack.paths import RuntimePaths, private, write_json, reject_links
from fittrack.storage_ops import verify_store


def validate_target(source, target):
    if not target.is_absolute():
        raise ValueError("新根目录必须是绝对路径")
    source, target = source.resolve(), target.resolve()
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("新旧根目录不能相同、相互包含或嵌套")
    if target.exists() and any(target.iterdir()):
        raise ValueError("新根目录必须为空，不能覆盖已有数据")
    return target


def relocate_root(source: Path, target: Path, bind_shortcuts=None):
    target = validate_target(source, target)
    paths = RuntimePaths.initialize(target)
    reject_links(source)
    original_marker = json.loads((source / "fittrack-root.json").read_text(encoding="utf-8"))
    write_json(target / "fittrack-root.json", original_marker | {"incomplete": True})
    for item in source.iterdir():
        if item.name in {"runtime", "tmp", "caches", "fittrack-root.json"}:
            continue
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copyfile(item, destination)
        files = item.rglob("*") if item.is_dir() else [item]
        for file in files:
            if file.is_file():
                copied = target / file.relative_to(source)

                def digest(path):
                    result = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            result.update(chunk)
                    return result.digest()

                if digest(file) != digest(copied):
                    raise ValueError("根目录复制文件哈希校验失败，原目录仍可使用")
    # The marker copied above must remain blocked until every database is verified.
    write_json(target / "fittrack-root.json", original_marker | {"incomplete": True})
    marker = json.loads((target / "fittrack-root.json").read_text(encoding="utf-8"))
    marker.pop("moved_to", None)
    hub = WorkspaceHub(paths)
    try:
        if hub.control.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("复制后的账号库校验失败")
        vault = CredentialStore(hub.control, paths)
        for row in hub.control.rows("SELECT id FROM users"):
            uid = row["id"]
            verify_store(hub.for_user(uid), uid)
            vault.snapshot_for(uid)
        with hub.control.lock:
            hub.control.db.execute("DELETE FROM sessions")
    finally:
        hub.close()
    private(target / "secrets" / "master.key")
    marker.pop("incomplete", None)
    write_json(target / "fittrack-root.json", marker)
    if bind_shortcuts:
        bind_shortcuts(target)
    old = json.loads((source / "fittrack-root.json").read_text(encoding="utf-8"))
    write_json(source / "fittrack-root.json", old | {"moved_to": str(target)})
    write_json(
        target / "runtime" / "relocated-from.json",
        {"source": str(source), "original_retained": True},
    )
    return paths
