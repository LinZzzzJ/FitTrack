"""Opt-in native launcher acceptance. Uses only explicitly named disposable roots."""

import base64
import ctypes
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from fittrack.desktop import create_shortcuts
from fittrack.paths import RuntimePaths

PROJECT = Path(__file__).resolve().parents[1]


def wait_ready(root, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state_file = root / "runtime/service.json"
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            response = requests.get(state["url"] + "/_local/health", timeout=1)
            if response.status_code == 200 and response.json()["instance"] == state["instance"]:
                return state
        except (OSError, ValueError, requests.RequestException):
            pass
        time.sleep(0.1)
    raise RuntimeError("Controlled QA service did not become ready")


def command(root, port, *extra):
    return [
        str(PROJECT / ".venv/Scripts/python.exe"),
        "-B",
        "-m",
        "fittrack",
        "--data-root",
        str(root),
        "--port",
        str(port),
        "--no-browser",
        "--no-shortcuts",
        *extra,
    ]


def main():
    if os.name != "nt":
        raise SystemExit("This acceptance checks native Windows pythonw and shortcuts")
    parent = PROJECT / "artifacts/native"
    parent.mkdir(parents=True, exist_ok=True)
    container = Path(tempfile.mkdtemp(prefix="run with spaces-", dir=parent))
    original = RuntimePaths.initialize(container / "original")
    original.configure_process()
    destination = container / "destination"
    # Read/write shortcut properties in a disposable installation, never the user's launch entry.
    fake_project = original.root / "caches/mock-install"
    (fake_project / ".venv/Scripts").mkdir(parents=True)
    (fake_project / ".venv/Scripts/pythonw.exe").touch()
    create_shortcuts(original.root, fake_project)
    literal = str(fake_project / "启动 FitTrack.lnk").replace("'", "''")
    script = f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{literal}'); @{{target=$s.TargetPath;arguments=$s.Arguments}} | ConvertTo-Json -Compress"
    shortcut = subprocess.check_output(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode(),
        ],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    shortcut = json.loads(shortcut.decode("utf-8", errors="replace"))
    assert shortcut["target"].endswith("pythonw.exe")
    assert "--data-root" in shortcut["arguments"] and "--background" in shortcut["arguments"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    args = command(original.root, port, "--background")
    args[0] = str(PROJECT / ".venv/Scripts/pythonw.exe")
    child = subprocess.Popen(args, cwd=PROJECT, creationflags=subprocess.CREATE_NO_WINDOW)
    active_root = original.root
    session = requests.Session()
    try:
        state = wait_ready(original.root)
        # No visible top-level window belongs to the launcher process.
        visible = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def window(hwnd, unused):
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == child.pid and ctypes.windll.user32.IsWindowVisible(hwnd):
                visible.append(hwnd)
            return True

        ctypes.windll.user32.EnumWindows(callback_type(window), 0)
        assert not visible
        response = subprocess.run(
            command(original.root, port), cwd=PROJECT, capture_output=True, timeout=15
        )
        assert response.returncode == 0
        assert wait_ready(original.root)["instance"] == state["instance"]
        second_root = RuntimePaths.initialize(container / "conflicting-root")
        conflict = subprocess.run(
            command(second_root.root, port), cwd=PROJECT, capture_output=True, timeout=15
        )
        assert conflict.returncode == 1
        assert not (second_root.root / "runtime/service.json").exists()
        missing = subprocess.run(
            command(container / "disconnected-drive", port),
            cwd=PROJECT,
            capture_output=True,
            timeout=15,
        )
        assert missing.returncode == 1 and not (container / "disconnected-drive").exists()
        base = state["url"]
        response = session.post(
            base + "/api/auth/register",
            json={"username": "native-test", "password": "native-test-password"},
            timeout=10,
        )
        assert response.status_code == 201
        session.put(
            base + "/api/settings", json={"api_key": "native-synthetic-key"}, timeout=10
        ).raise_for_status()
        response = session.post(
            base + "/api/local/root-migration", json={"path": str(destination)}, timeout=10
        )
        assert response.status_code == 202, response.text
        active_root = destination
        new_state = wait_ready(destination, timeout=45)
        child.wait(timeout=30)
        assert new_state["instance"] != state["instance"]
        assert json.loads((original.root / "fittrack-root.json").read_text())["moved_to"] == str(
            destination
        )
        assert session.get(base + "/api/me", timeout=10).status_code == 401
        session.post(
            base + "/api/auth/login",
            json={"username": "native-test", "password": "native-test-password"},
            timeout=10,
        ).raise_for_status()
        assert session.get(base + "/api/me", timeout=10).json()["ai"]["api_key_set"]
        previous_instance = new_state["instance"]
        restart_args = command(destination, port, "--restart", "--background")
        restart_args[0] = str(PROJECT / ".venv/Scripts/pythonw.exe")
        response = subprocess.Popen(
            restart_args,
            cwd=PROJECT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        child = response
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                latest = wait_ready(destination, timeout=1)
                if latest["instance"] != previous_instance:
                    break
            except RuntimeError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Graceful restart did not produce a new owned instance")
        assert latest["instance"] != previous_instance
        assert requests.get(base + "/api/version", timeout=5).json()["api_revision"] == 2
        assert session.get(base + "/api/me", timeout=5).status_code == 200
        session.post(
            base + "/api/meals",
            json={
                "date": "2026-10-15",
                "items": [
                    {
                        "name": "原生验收餐食",
                        "estimated_edible_grams": 100,
                        "kcal": 100,
                        "protein_g": 10,
                        "carbs_g": 10,
                        "fat_g": 2,
                    }
                ],
            },
            timeout=10,
        ).raise_for_status()
        from release_local import release

        report = release(destination)
        assert report["records_preserved"] and report["accounts_and_credentials_preserved"]
        assert report["backups"] and report["paid_requests"] == 0
        assert session.get(base + "/api/days/2026-10-15", timeout=5).json()["totals"]["kcal"] == 100
        print(
            json.dumps(
                {
                    "checks": [
                        "pythonw hidden window",
                        "root-bound shortcuts",
                        "duplicate launch reuse",
                        "port conflict without fallback",
                        "missing root without fallback",
                        "whole root migration and restart",
                        "sessions invalidated",
                        "encrypted credential preserved",
                        "graceful restart waits for old state and port; preserves login and credentials",
                        "release helper backs up health rows and verifies live source identity and unchanged credentials",
                    ],
                    "test_root": str(container),
                },
                ensure_ascii=False,
            )
        )
    finally:
        for root in (active_root, original.root):
            if (root / "runtime/service.json").is_file():
                subprocess.run(
                    command(root, port, "--stop"), cwd=PROJECT, capture_output=True, timeout=30
                )
        deadline = time.monotonic() + 15
        while (active_root / "runtime/service.json").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        session.close()


if __name__ == "__main__":
    main()
