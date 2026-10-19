"""Test the actual ZIP in an unrelated Unicode installation with no dev PATH."""

import argparse
import base64
import ctypes
import io
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import zipfile
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests
from PIL import Image

from browser_check import OfflineAI

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-10-15"
AI = OfflineAI()


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.reply({"data": [{"id": "deepseek-flash"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["messages"][0]["content"]
        if "effective_met" in prompt:
            result, _ = AI.cardio_estimate({}, {"input": {"description": "休息较多"}})
        elif "protein_target_g" in prompt:
            result, _ = AI.goals({}, {})
        elif "next_day_advice" in prompt:
            result, _ = AI.feedback({}, {})
        elif "basis_kind" in prompt:
            result, _ = AI.meal_label({}, None, "")
            result["fat_g"] = 1.1
        else:
            result, _ = AI.meal({}, None, "")
        self.reply(
            {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                "usage": {"total_tokens": 0},
            }
        )

    def reply(self, data):
        encoded = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def wait_state(root, timeout=30, exclude=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = json.loads((root / "runtime/service.json").read_text(encoding="utf-8"))
            response = requests.get(state["url"] + "/_local/health", timeout=1)
            if (
                response.ok
                and response.json()["instance"] == state["instance"]
                and state["instance"] != exclude
            ):
                return state
        except (OSError, ValueError, requests.RequestException):
            pass
        time.sleep(0.1)
    raise RuntimeError("Portable service not ready: " + str(root))


def dialog_action(child, accept, expected_exit=0):
    user = ctypes.windll.user32
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    found = []

    @callback
    def each(hwnd, data):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        cls = ctypes.create_unicode_buffer(100)
        user.GetClassNameW(hwnd, cls, len(cls))
        if pid.value == child.pid and cls.value == "#32770":
            found.append(hwnd)
        return True

    deadline = time.monotonic() + 12
    while not found and time.monotonic() < deadline and child.poll() is None:
        user.EnumWindows(each, 0)
        time.sleep(0.05)
    assert found, "Owned native directory dialog did not appear"
    user.PostMessageW(found[0], 0x111 if accept else 0x10, 1 if accept else 0, 0)
    assert child.wait(12) == expected_exit


def main(archive):
    folder = ROOT / "artifacts/portable"
    folder.mkdir(parents=True, exist_ok=True)
    qa = Path(tempfile.mkdtemp(prefix="实际成品 中文 spaces-", dir=folder))
    install = qa / "独立安装目录"
    install.mkdir()
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            assert (install / entry.filename).resolve().is_relative_to(install.resolve())
        zipped.extractall(install)
    exe = install / "FitTrack/FitTrack.exe"
    data = qa / "自选 数据目录"
    data.mkdir()
    scratch = qa / "tmp"
    scratch.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX", "VIRTUAL_ENV"}
        and not key.startswith("_PYI_")
    }
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    for key in ("TEMP", "TMP", "TMPDIR"):
        env[key] = str(scratch)

    def command(*args):
        return subprocess.run(
            [str(exe), *map(str, args)],
            cwd=qa,
            env=env,
            timeout=35,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    checks = []
    assert command("--data-root", data, "--self-check").returncode == 0
    check = json.loads((data / "caches/portable-check.json").read_text(encoding="utf-8"))
    assert all(str(install) in path for path in check["module_locations"])
    checks.append(
        "isolated PATH, Python 3.13, native modules, TLS, crypto, SQLite, four image formats"
    )
    # First run cancellation and helper communication must not rely on console stdout.
    first = subprocess.Popen([str(exe)], cwd=qa, env=env)
    dialog_action(first, False)
    checks.append("first setup native dialog cancellation")
    for accept in (False, True):
        output = data / "tmp/picker-result.json"
        child = subprocess.Popen(
            [str(exe), "--desktop-pick", "--initial", str(data), "--output", str(output)],
            cwd=qa,
            env=env,
        )
        dialog_action(child, accept)
        chosen = json.loads(output.read_text(encoding="utf-8"))["path"]
        assert (Path(chosen) == data) if accept else chosen is None
        output.unlink()
    checks.append("native directory picker accept and cancel via controlled result file")
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    service = subprocess.Popen(
        [str(exe), "--data-root", str(data), "--port", str(port), "--no-browser"], cwd=qa, env=env
    )
    active = data
    client = requests.Session()
    try:
        state = wait_state(active)
        base = state["url"]

        def api(method, path, body=None, expected=200):
            response = client.request(method, base + "/api" + path, json=body, timeout=8)
            assert response.status_code == expected, (
                path,
                response.status_code,
                response.text[:300],
            )
            return response.json() if response.content else None

        def job(payload):
            payload = payload | {"request_key": os.urandom(10).hex()}
            task = api("POST", "/jobs", payload, 202)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                task = api("GET", "/jobs/" + task["id"])
                if task["status"] not in {"queued", "running"}:
                    assert task["status"] == "done", task.get("error")
                    return task
                time.sleep(0.05)
            raise AssertionError("Mock AI task timed out")

        def operation(path, body=None):
            task = api("POST", path, body, 202)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                task = api("GET", "/storage/operations/" + task["id"])
                if task["status"] not in {"queued", "running"}:
                    assert task["status"] == "done", task
                    return task
                time.sleep(0.1)
            raise AssertionError("Storage operation timed out")

        info = requests.get(base + "/api/version", timeout=3).json()
        assert (
            info["distribution"] == "portable"
            and info["version"] == "0.4.0"
            and not info["restart_required"]
        )
        assert command("--data-root", data, "--port", port, "--no-browser").returncode == 0
        assert wait_state(data)["instance"] == state["instance"]
        conflict = qa / "端口冲突目录"
        conflict.mkdir()
        rejected = subprocess.Popen(
            [str(exe), "--data-root", str(conflict), "--port", str(port), "--no-browser"],
            cwd=qa,
            env=env,
        )
        dialog_action(rejected, False, expected_exit=1)
        assert not (conflict / "runtime/service.json").exists()
        missing = subprocess.Popen(
            [str(exe), "--data-root", str(qa / "missing-directory"), "--no-browser"],
            cwd=qa,
            env=env,
        )
        dialog_action(missing, False, expected_exit=1)
        assert not (qa / "missing-directory").exists()
        checks.append("port conflict and missing data directory fail visibly without fallback")
        shortcuts = list(exe.parent.glob("*.lnk"))
        assert len(shortcuts) == 4
        literal = str(exe.parent / "启动 FitTrack.lnk").replace("'", "''")
        script = f"$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $s=(New-Object -ComObject WScript.Shell).CreateShortcut('{literal}'); @{{target=$s.TargetPath;arguments=$s.Arguments}} | ConvertTo-Json -Compress"
        ps = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        shortcut = json.loads(
            subprocess.check_output(
                [
                    ps,
                    "-NoProfile",
                    "-EncodedCommand",
                    base64.b64encode(script.encode("utf-16-le")).decode(),
                ],
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).decode("utf-8", errors="replace")
        )
        assert (
            Path(shortcut["target"]) == exe
            and "--data-root" in shortcut["arguments"]
            and "python" not in shortcut["arguments"]
        )
        checks.append("EXE shortcuts and repeat start reuse same instance")
        credentials = {"username": "portable-alice", "password": "offline-alice-password"}
        api("POST", "/auth/register", credentials, 201)
        assert not api("GET", "/me")["ai"]["api_key_set"]
        settings = {
            "base_url": f"http://127.0.0.1:{provider.server_port}",
            "api_key": "portable-synthetic-key",
            "remember": True,
        }
        api("PUT", "/settings", settings)
        api("POST", "/settings/test-connection")
        profile = {
            "effective_date": DAY,
            "height_cm": 175,
            "initial_weight_kg": 75,
            "sex": "male",
            "resting_kcal": 1800,
            "activity_factor": 1.2,
            "target_weight_kg": 65,
        }
        api("PUT", "/profile", profile)
        api("PUT", "/body", {"date": DAY, "weight_kg": 75})
        for format_name in ("JPEG", "PNG", "WEBP", "GIF"):
            stream = io.BytesIO()
            Image.new("RGB", (50, 70), "orange").save(stream, format_name)
            response = client.post(
                base + "/api/uploads",
                files={
                    "file": (
                        "sample." + format_name.lower(),
                        stream.getvalue(),
                        "image/" + format_name.lower(),
                    )
                },
                timeout=8,
            )
            assert response.status_code == 201, response.text
            image = response.json()
        photo = job({"kind": "meal", "date": DAY, "image_id": image["id"], "note": "只吃蛋白"})
        meal = {
            "date": DAY,
            "slot": "lunch",
            "items": photo["result"]["items"],
            "image_id": image["id"],
            "source_job_id": photo["id"],
        }
        saved = api("POST", "/meals", meal, 201)
        assert api("POST", "/meals", meal, 201)["id"] == saved["id"]
        label = job(
            {
                "kind": "meal",
                "meal_mode": "label",
                "date": DAY,
                "image_id": image["id"],
                "note": "每袋60克，两袋",
            }
        )
        labelled = meal | {
            "source_job_id": label["id"],
            "nutrition_label": {
                "label": label["result"]["label"],
                "portion": {"mode": "grams", "grams": 120},
            },
        }
        preview = api("POST", "/nutrition-label/preview", labelled["nutrition_label"])
        assert preview["item"]["kcal"] == 107.27
        label_entry = api("POST", "/meals", labelled, 201)
        api("DELETE", "/jobs/" + label["id"], expected=204)
        api(
            "PUT",
            "/meals/" + label_entry["id"],
            labelled | {"source_job_id": None, "note": "still editable"},
        )
        assert api("GET", f"/days/{DAY}")["totals"]["kcal"] == 407.27
        checks.append(
            "four image uploads, photo and label AI, authoritative calories, idempotence, delete and edit"
        )
        plan = api(
            "POST",
            "/plans",
            {
                "date": DAY,
                "title": "力量计划",
                "kind": "strength",
                "activity": "strength",
                "duration_minutes": 40,
            },
            201,
        )
        workout = {
            "date": DAY,
            "title": "力量实际",
            "kind": "strength",
            "activity": "strength",
            "duration_minutes": 40,
            "plan_id": plan["id"],
            "exercises": [{"name": "卧推", "sets": [{"reps": 10, "weight_kg": 40}]}],
        }
        api("POST", "/workouts", workout, 201)
        cardio_input = {
            "kind": "cardio",
            "activity": "badminton",
            "duration_minutes": 60,
            "intensity": "moderate",
            "description": "休息较多",
        }
        estimate = job({"kind": "cardio_estimate", "date": DAY, "cardio_input": cardio_input})
        assert estimate["result"]["estimate"]["net_kcal"] == 375
        cardio = {
            "date": DAY,
            "title": "羽毛球",
            "kind": "cardio",
            "activity": "badminton",
            "duration_minutes": 60,
            "intensity": "moderate",
            "note": "休息较多",
            "met": 6,
            "ai_estimate_job_id": estimate["id"],
        }
        api("POST", "/workouts", cardio, 201)
        job({"kind": "goals", "date": DAY, "goal_profile": profile})
        job({"kind": "feedback", "date": DAY})
        api("POST", f"/days/{DAY}/complete")
        api("GET", f"/trends?start={DAY}&end=2026-10-17&measurement_start={DAY}")
        api("GET", "/weekly-review")
        api("GET", "/diet-history?start=2026-10-15&end=2026-10-21")
        checks.append(
            "strength, plan, badminton AI 375 kcal, goals, daily feedback, weekly gate, trends and history"
        )
        other = requests.Session()
        assert (
            other.post(
                base + "/api/auth/register",
                json={"username": "portable-bob", "password": "offline-bob-password"},
            ).status_code
            == 201
        )
        assert not other.get(base + "/api/me").json()["ai"]["api_key_set"]
        assert not other.get(base + f"/api/days/{DAY}").json()["meals"]
        assert other.get(base + "/api/images/" + image["id"]).status_code == 404
        backup = operation("/backups")["result"]["backup_id"]
        operation("/storage/migrate", {"path": "personal/独立工作区"})
        operation("/backups/restore", {"backup_id": backup})
        assert api("GET", f"/days/{DAY}")["totals"]["kcal"] == 407.27
        checks.append(
            "account/key/image isolation, encrypted credentials, backup, workspace migration and restore"
        )
        destination = qa / "迁移后的 数据目录"
        api("POST", "/local/root-migration", {"path": str(destination)}, 202)
        active = destination
        new_state = wait_state(active, 45)
        assert new_state["instance"] != state["instance"]
        api("POST", "/auth/login", credentials)
        assert api("GET", "/me")["ai"]["api_key_set"]
        assert api("GET", f"/days/{DAY}")["totals"]["kcal"] == 407.27
        restarted = subprocess.Popen(
            [
                str(exe),
                "--data-root",
                str(active),
                "--port",
                str(port),
                "--restart",
                "--no-browser",
            ],
            cwd=qa,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert (
            wait_state(active, exclude=new_state["instance"])["instance"] != new_state["instance"]
        )
        assert restarted.poll() is None
        assert service.poll() is not None
        checks.append(
            "whole-root migration re-exec and graceful restart with records/key preserved"
        )
        report = {
            "checks": checks,
            "platform": os.sys.getwindowsversion().build,
            "windows10_actual_test": False,
            "paid_requests": 0,
            "archive": str(archive),
            "qa_root": str(qa),
            "sanitized_path": env["PATH"],
        }
        (qa / "acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=True), flush=True)
    finally:
        try:
            state = json.loads((active / "runtime/service.json").read_text(encoding="utf-8"))
            requests.post(
                state["url"] + "/_local/stop",
                headers={"x-fittrack-management": state["token"]},
                json={},
                timeout=4,
            )
        except (OSError, ValueError, requests.RequestException):
            pass
        provider.shutdown()
        client.close()
        deadline = time.monotonic() + 15
        while (active / "runtime/service.json").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not (active / "runtime/service.json").exists(), "Owned QA service did not stop"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    main(parser.parse_args().archive.resolve())
