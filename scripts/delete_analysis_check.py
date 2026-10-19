"""Exercise irreversible analysis deletion using isolated records and no AI calls."""

import io
import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from PIL import Image
from playwright.sync_api import expect, sync_playwright

from browser_check import OfflineAI
from fittrack.app import create_app
from fittrack.control import WorkspaceHub
from fittrack.credentials import CredentialStore
from fittrack.models import JobRequest, Meal, Profile
from fittrack.nutrition import label_food
from fittrack.paths import RuntimePaths

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-10-15"


def main():
    checks = ROOT / "artifacts/browser"
    checks.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="delete-", dir=checks))
    paths = RuntimePaths.initialize(root)
    paths.configure_process()
    screenshots = root / "caches/screenshots"
    screenshots.mkdir()
    store = WorkspaceHub(paths)
    vault = CredentialStore(store.control, paths)
    app = create_app(store, vault, ai=OfflineAI())
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    base = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=1))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    errors, console_errors = [], []
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(root / "caches/browser-profile"),
                downloads_path=str(root / "tmp/downloads"),
                channel="msedge",
                headless=True,
                viewport={"width": 1440, "height": 1050},
                locale="zh-CN",
            )
            try:
                page = context.new_page()
                uid = page.request.post(
                    base + "/api/auth/register",
                    data={
                        "username": "delete-browser",
                        "password": "offline-password-123",
                    },
                ).json()["id"]
                profile = Profile(
                    effective_date=DAY, height_cm=175, initial_weight_kg=75, resting_kcal=1800
                ).model_dump(mode="json")
                assert page.request.put(base + "/api/profile", data=profile).status == 200
                photo = io.BytesIO()
                Image.new("RGB", (90, 120), "orange").save(photo, "PNG")
                image = store.put_image(uid, photo.getvalue())
                labels = {
                    "label": {
                        "name": "label-test",
                        "basis_kind": "per_100g",
                        "basis_grams": 100,
                        "energy_value": 374,
                        "energy_unit": "kJ",
                        "protein_g": 13.2,
                        "carbs_g": 6.4,
                        "fat_g": 1.1,
                        "assumptions": [],
                    },
                    "portion": {"mode": "packs", "pack_grams": 60, "packs": 1},
                }
                jobs = []
                fixtures = [
                    ("photo-booked", "done", "photo", True),
                    ("label-booked", "done", "label", True),
                    ("photo-draft", "done", "photo", False),
                    ("label-failed", "failed", "label", False),
                    ("photo-interrupted", "interrupted", "photo", False),
                    ("photo-queued", "queued", "photo", False),
                    ("label-running", "running", "label", False),
                ]
                for note, status, mode, booked in fixtures:
                    request = JobRequest(
                        kind="meal",
                        date=DAY,
                        image_id=image["id"],
                        note=note,
                        meal_mode=mode,
                        slot="lunch",
                        request_key=note,
                    )
                    job, _ = store.create_job(uid, request.model_dump(mode="json"))
                    result = {"label": labels["label"]} if mode == "label" else {"items": []}
                    store.update_job(
                        uid, job["id"], status, result=result if status == "done" else None
                    )
                    jobs.append(job)
                    if booked:
                        meal = Meal(
                            date=DAY,
                            slot="lunch",
                            image_id=image["id"],
                            source_job_id=job["id"],
                            items=[label_food(labels)],
                            nutrition_label=labels if mode == "label" else None,
                        )
                        store.save_entry(uid, "meal", meal.model_dump(mode="json"))
                before = page.request.get(base + f"/api/days/{DAY}").json()
                expected_failure = False
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console_errors.append(message.text)
                        if message.type == "error"
                        and not (
                            expected_failure and "/api/jobs/" in message.location.get("url", "")
                        )
                        else None
                    ),
                )
                page.goto(base)
                page.get_by_role("navigation").get_by_role(
                    "button", name="饮食记录", exact=True
                ).click()
                expect(page.locator(".job-row")).to_have_count(7)
                for note in ["photo-queued", "label-running"]:
                    row = page.locator(".job-row").filter(has_text=note)
                    expect(
                        row.get_by_role("button", name="删除照片分析记录", exact=True)
                    ).to_be_disabled()
                    expect(row.get_by_text("分析结束后可删除", exact=True)).to_be_visible()
                watcher = context.new_page()
                watcher.goto(base)
                watcher.get_by_role("navigation").get_by_role(
                    "button", name="饮食记录", exact=True
                ).click()
                expect(watcher.locator(".job-row")).to_have_count(7)
                row = page.locator(".job-row").filter(has_text="photo-booked")
                row.get_by_role("button", name="删除照片分析记录", exact=True).click()
                dialog = page.get_by_role("dialog", name="删除这条照片分析记录？", exact=True)
                expect(dialog).to_contain_text(DAY + " · 午餐")
                expect(dialog).to_contain_text("删除后无法在页面撤销或恢复")
                dialog.get_by_role("button", name="取消", exact=True).click()
                expect(row).to_be_visible()
                row.get_by_role("button", name="删除照片分析记录", exact=True).click()
                pattern = f"**/api/jobs/{jobs[0]['id']}"
                expected_failure = True
                page.route(
                    pattern,
                    lambda route: route.fulfill(
                        status=409, json={"detail": "模拟冲突，请稍后重试"}
                    ),
                )
                dialog.get_by_role("button", name="确认删除", exact=True).click()
                expect(dialog.get_by_role("alert")).to_have_text("模拟冲突，请稍后重试")
                expect(dialog).to_be_visible()
                page.unroute(pattern)
                expected_failure = False
                pending = []
                page.route(pattern, lambda route: pending.append(route))
                dialog.get_by_role("button", name="确认删除", exact=True).click()
                expect(dialog.get_by_role("button", name="删除中…", exact=True)).to_be_disabled()
                expect(dialog.get_by_role("button", name="取消", exact=True)).to_be_disabled()
                deadline = time.monotonic() + 5
                while not pending and time.monotonic() < deadline:
                    page.wait_for_timeout(20)
                dialog.get_by_role("button", name="删除中…", exact=True).evaluate(
                    "button => { button.click(); button.click(); }"
                )
                assert len(pending) == 1
                pending[0].continue_()
                expect(dialog).not_to_be_visible()
                page.unroute(pattern)
                expect(row).to_have_count(0)
                expect(watcher.locator(".job-row")).to_have_count(6)
                watcher.close()
                page.set_viewport_size({"width": 390, "height": 844})
                row = page.locator(".job-row").filter(has_text="label-booked")
                row.get_by_role("button", name="删除照片分析记录", exact=True).click()
                expect(dialog).to_be_visible()
                page.wait_for_function("document.documentElement.scrollWidth <= innerWidth")
                dialog.screenshot(path=str(screenshots / "delete-confirm-mobile.png"))
                dialog.get_by_role("button", name="确认删除", exact=True).click()
                expect(dialog).not_to_be_visible()
                for note in ["photo-draft", "label-failed", "photo-interrupted"]:
                    row = page.locator(".job-row").filter(has_text=note)
                    row.get_by_role("button", name="删除照片分析记录", exact=True).click()
                    dialog.get_by_role("button", name="确认删除", exact=True).click()
                    expect(dialog).not_to_be_visible()
                    expect(row).to_have_count(0)
                page.reload()
                page.get_by_role("button", name="打开导航", exact=True).click()
                page.get_by_role("navigation").get_by_role(
                    "button", name="饮食记录", exact=True
                ).click()
                expect(page.locator(".job-row")).to_have_count(2)
                after = page.request.get(base + f"/api/days/{DAY}").json()
                assert after["totals"] == before["totals"]
                assert after["deficit_kcal"] == before["deficit_kcal"]
                assert len(after["meals"]) == 2
                assert all(meal["source_job_id"] is None for meal in after["meals"])
                assert (
                    page.request.get(base + f"/api/images/{image['id']}").body() == photo.getvalue()
                )
                page.locator(".meal-card").filter(has_text="标签换算").get_by_role(
                    "button", name="编辑餐食", exact=True
                ).click()
                page.get_by_role("button", name="计算实际摄入", exact=True).click()
                page.get_by_role("button", name="保存标签修改", exact=True).click()
                page.get_by_text("标签餐食已确认入账", exact=True).wait_for()
                page.wait_for_function("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(screenshots / "delete-results-mobile.png"), full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1050})
                page.screenshot(
                    path=str(screenshots / "delete-results-desktop.png"), full_page=True
                )
                assert not errors, errors
                assert not console_errors, console_errors
                print(
                    json.dumps(
                        {
                            "checks": [
                                "cancel",
                                "failure retains dialog",
                                "one pending request",
                                "active tasks disabled",
                                "confirmed photo and label meals preserved",
                                "draft failed interrupted delete",
                                "SSE second page refresh",
                                "permanent after reload",
                                "image unchanged",
                                "retained meal editable",
                                "desktop and narrow window",
                            ],
                            "runtime_errors": errors,
                            "paid_requests": 0,
                            "screenshots": str(screenshots),
                        },
                        ensure_ascii=True,
                    )
                )
            finally:
                context.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("QA server did not shut down")
        store.close()


if __name__ == "__main__":
    main()
