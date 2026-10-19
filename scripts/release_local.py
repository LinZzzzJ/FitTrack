"""Backup, gracefully replace, and verify an explicitly selected local instance.

Never imports credentials or makes provider requests. No test rows are written.
"""

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from fittrack.control import HEALTH_TABLES
from fittrack.paths import RuntimePaths, reject_links, write_json
from fittrack.storage_ops import MAX_ARCHIVE, validate_rows
from fittrack.store import encode
from fittrack.version import API_REVISION, source_fingerprint

PROJECT = Path(__file__).resolve().parents[1]


def read_api(url, token=None):
    request = urllib.request.Request(
        url,
        data=b"{}" if token else None,
        headers={"x-fittrack-management": token} if token else {},
    )
    with urllib.request.urlopen(request, timeout=4) as response:
        return json.load(response)


def readonly(path):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("BEGIN")
    return connection


def snapshot(root):
    control = readonly(root / "control/accounts.sqlite3")
    try:
        core = {
            table: [dict(row) for row in control.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("users", "ai", "workspaces")
        }
    finally:
        control.close()
    spaces = {}
    for mapping in core["workspaces"]:
        uid = mapping["user_id"]
        workspace = (root / mapping["path"]).resolve()
        if not workspace.is_relative_to(root):
            raise ValueError("工作区越界，未执行更新")
        database = readonly(workspace / "fittrack.sqlite3")
        try:
            tables = {
                table: [
                    dict(row)
                    for row in database.execute(
                        f"SELECT * FROM {table} WHERE user_id=? ORDER BY rowid", (uid,)
                    )
                ]
                for table in HEALTH_TABLES
            }
        finally:
            database.close()
        if any(job["status"] in {"queued", "running"} for job in tables["jobs"]):
            raise ValueError("存在未结束AI任务，暂不更新")
        validate_rows(tables)
        spaces[uid] = {"path": workspace, "tables": tables}
    for file in (root / "runtime/operations").glob("*.json"):
        if json.loads(file.read_text(encoding="utf-8"))["status"] in {"queued", "running"}:
            raise ValueError("存在未结束数据管理操作，暂不更新")
    digest = hashlib.sha256(encode(core).encode()).hexdigest()
    master = hashlib.sha256((root / "secrets/master.key").read_bytes()).hexdigest()
    return spaces, (digest, master)


def save_backups(root, spaces):
    backups = []
    for uid, space in spaces.items():
        ident = secrets.token_hex(12)
        folder = root / "backups" / uid
        folder.mkdir(exist_ok=True)
        temp = root / "tmp" / f"{ident}.zip.part"
        target = folder / f"{ident}.zip"
        try:
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "manifest.json",
                    encode({"format": "fittrack-health", "version": 1, "tables": space["tables"]}),
                )
                for item in space["tables"]["images"]:
                    name = f"{item['sha']}.{item['ext']}"
                    source = space["path"] / "images" / name
                    if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha"]:
                        raise ValueError("原照片哈希校验失败，未切换服务")
                    archive.write(source, "images/" + name)
            if temp.stat().st_size > MAX_ARCHIVE:
                raise ValueError("备份超出体积限制，未切换服务")
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        backups.append(str(target.relative_to(root)))
    return backups


def release(root):
    if not root.is_absolute():
        raise ValueError("必须指定绝对数据根目录")
    root = root.resolve(strict=True)
    reject_links(root)
    marker = json.loads((root / "fittrack-root.json").read_text(encoding="utf-8"))
    RuntimePaths(root).configure_process()
    state_file = root / "runtime/service.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    health = read_api(state["url"] + "/_local/health")
    if health["root_id"] != marker["id"] or health["instance"] != state["instance"]:
        raise ValueError("当前实例与绑定根目录不一致，未停止任何服务")
    before, credentials = snapshot(root)
    backups = save_backups(root, before)
    try:
        read_api(state["url"] + "/_local/stop", state["token"])
    except urllib.error.HTTPError:
        raise
    except OSError:
        # The server may close the socket before the stop acknowledgement arrives.
        # Observe the owned state disappearing; do not resend or kill anything.
        pass
    deadline = time.monotonic() + 45
    while state_file.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("旧服务尚未退出，未强制终止或启动第二实例；备份已保留")
        time.sleep(0.25)
    stopped, stopped_credentials = snapshot(root)
    if encode({uid: data["tables"] for uid, data in before.items()}) != encode(
        {uid: data["tables"] for uid, data in stopped.items()}
    ):
        backups.extend(save_backups(root, stopped))
    if credentials != stopped_credentials:
        raise RuntimeError("停止期间账号或凭据发生变化，已保留原文件及备份，请核对后启动")
    args = [
        str(PROJECT / ".venv/Scripts/pythonw.exe"),
        "-B",
        "-m",
        "fittrack",
        "--background",
        "--data-root",
        str(root),
        "--port",
        str(urlparse(state["url"]).port),
        "--no-browser",
    ]
    subprocess.Popen(
        args, cwd=PROJECT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )
    deadline = time.monotonic() + 45
    while True:
        try:
            current = read_api(state["url"] + "/_local/health")
            info = read_api(state["url"] + "/api/version")
            if current["instance"] != state["instance"]:
                break
        except (OSError, ValueError, urllib.error.URLError):
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("新版服务未就绪，原数据及备份保留，未改用其他根目录")
        time.sleep(0.25)
    if (
        current["root_id"] != marker["id"]
        or info["api_revision"] != API_REVISION
        or info["backend_build"] != source_fingerprint()
        or info["restart_required"]
    ):
        raise RuntimeError("新版正式实例的版本核验未通过")
    after, after_credentials = snapshot(root)
    records_match = encode({uid: data["tables"] for uid, data in stopped.items()}) == encode(
        {uid: data["tables"] for uid, data in after.items()}
    )
    if not records_match or credentials != after_credentials:
        raise RuntimeError("更新后数据核验不一致，请保留备份核对；未自动覆盖用户数据")
    report = {
        "version": info["version"],
        "api_revision": info["api_revision"],
        "instance_changed": True,
        "same_root": True,
        "records_preserved": records_match,
        "accounts_and_credentials_preserved": True,
        "record_counts": [
            {table: len(rows) for table, rows in space["tables"].items()}
            for space in after.values()
        ],
        "backups": backups,
        "paid_requests": 0,
    }
    write_json(root / "runtime/update-verification.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="备份、正常重启并核验指定本机实例")
    parser.add_argument("--data-root", type=Path, required=True)
    print(json.dumps(release(parser.parse_args().data_root), ensure_ascii=True))
