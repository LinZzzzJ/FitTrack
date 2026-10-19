"""Smoke-test the distributed frontend and offline guide with an owned Edge profile."""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from check_portable_release import wait_state

ROOT = Path(__file__).resolve().parents[1]


def main(archive):
    parent = ROOT / "artifacts/portable-ui"
    parent.mkdir(parents=True, exist_ok=True)
    qa = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    install = qa / "install"
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            assert (install / item.filename).resolve().is_relative_to(install.resolve())
        zipped.extractall(install)
    data = qa / "data"
    data.mkdir()
    scratch = qa / "tmp"
    scratch.mkdir()
    env = dict(os.environ)
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    for key in ("PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX", "VIRTUAL_ENV"):
        env.pop(key, None)
    for key in ("TMP", "TEMP", "TMPDIR"):
        env[key] = os.environ[key] = str(scratch)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    child = subprocess.Popen(
        [
            str(install / "FitTrack/FitTrack.exe"),
            "--data-root",
            str(data),
            "--port",
            str(port),
            "--no-browser",
            "--no-shortcuts",
        ],
        env=env,
        cwd=qa,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    state = None
    try:
        state = wait_state(data)
        base = state["url"]
        client = requests.Session()
        credentials = {"username": "release-ui", "password": "offline-ui-password"}
        assert client.post(base + "/api/auth/register", json=credentials).status_code == 201
        profile = {
            "effective_date": "2026-10-15",
            "height_cm": 175,
            "initial_weight_kg": 75,
            "sex": "male",
            "resting_kcal": 1800,
            "activity_factor": 1.2,
            "target_weight_kg": 65,
            "calorie_target": 1800,
        }
        assert client.put(base + "/api/profile", json=profile).ok
        for day, weight, fat in ((15, 75, 22), (16, 74.8, 21.9), (17, 74.7, 21.8)):
            assert client.put(
                base + "/api/body",
                json={
                    "date": f"2026-10-{day}",
                    "weight_kg": weight,
                    "body_fat_pct": fat,
                },
            ).ok
        client.close()
        version = requests.get(base + "/api/version", timeout=4).json()
        assert version["version"] == "0.4.0" and version["distribution"] == "portable"
        assert not version["restart_required"]
        screenshots = qa / "screenshots"
        screenshots.mkdir()
        errors = []
        overflow = []
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(data / "caches/edge-qa-profile"),
                downloads_path=str(scratch / "downloads"),
                channel="msedge",
                headless=True,
                viewport={"width": 1440, "height": 1050},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                reduced_motion="reduce",
            )
            try:
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base)
                page.get_by_label("用户名", exact=True).fill(credentials["username"])
                page.get_by_label("密码", exact=True).fill(credentials["password"])
                page.get_by_role("button", name="登录", exact=True).click()
                page.get_by_role("navigation", name="主导航").wait_for()
                for title, name in (
                    ("今日概览", "dashboard"),
                    ("身体记录", "body"),
                    ("饮食记录", "meals"),
                    ("训练与排期", "training"),
                    ("趋势分析", "trends"),
                    ("个人设置", "settings"),
                ):
                    page.get_by_role("navigation", name="主导航").get_by_role(
                        "button", name=title, exact=True
                    ).click()
                    page.wait_for_timeout(800)
                    assert not page.get_by_text("后台需要重启", exact=True).is_visible()
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (
                        title
                    )
                    if name in {"dashboard", "trends", "settings"}:
                        page.screenshot(path=str(screenshots / (name + ".png")), full_page=True)
                assert page.get_by_label("API Key", exact=True).get_attribute("type") == "password"
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(700)
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                page.screenshot(path=str(screenshots / "settings-mobile.png"), full_page=True)
                guide = context.new_page()
                network = []
                guide.on(
                    "request",
                    lambda request: (
                        network.append(request.url)
                        if request.url.startswith(("http:", "https:"))
                        else None
                    ),
                )
                guide.on("pageerror", lambda error: errors.append(str(error)))
                guide.goto((install / "FitTrack/首次使用指南.html").as_uri())
                assert guide.locator("section").count() == 6
                for width, height in ((1440, 1050), (390, 844)):
                    guide.set_viewport_size({"width": width, "height": height})
                    guide.wait_for_timeout(200)
                    too_wide = guide.evaluate("document.documentElement.scrollWidth > innerWidth")
                    overflow.append(too_wide)
                    assert not too_wide, f"Guide overflow at {width}px"
                    guide.screenshot(path=str(screenshots / f"guide-{width}.png"), full_page=True)
                assert not network, "Offline guide requested external resources"
                assert not errors, errors
            finally:
                context.close()
        report = {
            "version": version,
            "ui_pages": 6,
            "guide_sections": 6,
            "horizontal_overflow": overflow,
            "runtime_errors": errors,
            "paid_requests": 0,
            "qa_root": str(qa),
        }
        (qa / "acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=True), flush=True)
    finally:
        if state:
            try:
                requests.post(
                    state["url"] + "/_local/stop",
                    json={},
                    headers={"x-fittrack-management": state["token"]},
                    timeout=4,
                )
            except requests.RequestException:
                pass
        assert child.wait(20) == 0
        deadline = time.monotonic() + 5
        while (data / "runtime/service.json").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not (data / "runtime/service.json").exists()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    main(parser.parse_args().archive.resolve())
