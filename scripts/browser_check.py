"""Browser acceptance with a temporary database and offline AI contract stub."""

import io
import base64
import json
import re
import socket
import tempfile
import threading
import time
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch

import uvicorn
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

from fittrack.app import create_app
from fittrack.control import WorkspaceHub
from fittrack.credentials import CredentialStore
from fittrack.paths import RuntimePaths

ROOT = Path(__file__).resolve().parents[1]


def today():
    return "2026-10-15"


def photo_transfer(page, files):
    """Use the browser's File/DataTransfer API to exercise actual drop handlers."""
    return page.evaluate_handle(
        """files => {
          const transfer = new DataTransfer();
          for (const file of files) {
            const bytes = Uint8Array.from(atob(file.data), c => c.charCodeAt(0));
            transfer.items.add(new File([bytes], file.name, {type: file.type}));
          }
          return transfer;
        }""",
        files,
    )


class OfflineAI:
    weekly_calls = 0

    def meal_label(self, config, path, note):
        return {
            "name": "鸡胸肉丸",
            "basis_kind": "per_100g",
            "basis_grams": 100,
            "energy_value": 374,
            "energy_unit": "kJ",
            "protein_g": 13.2,
            "carbs_g": 6.4,
            "fat_g": None,
            "assumptions": ["脂肪未辨读，请按包装补充"],
        }, {"total_tokens": 0}

    def cardio_estimate(self, config, context):
        return {
            "effective_met": 6,
            "rationale": "结合羽毛球强度及中间休息较多的描述，整段按平均 MET 6 估算。",
            "assumptions": [context["input"]["description"], "总时长包含休息，净消耗由后端计算。"],
        }, {"total_tokens": 0}

    def weekly_review(self, config, context):
        self.weekly_calls += 1
        return {
            "summary": "这一周已完成七天记录，饮食与训练都有迹可循。",
            "diet_findings": ["优先核对实际份量，保持蛋白质与蔬菜摄入。"],
            "training_findings": ["力量和有氧配合，休息日也属于训练节奏。"],
            "next_week_plan": ["延续记录，按恢复情况安排两次力量与适量有氧。"],
            "limitations": ["仅分析主动确认的餐食；测量不足时不推断身体变化。"],
        }, {"total_tokens": 0}

    def goals(self, config, context):
        return {
            "calorie_target": 1800,
            "protein_target_g": 120,
            "carbs_target_g": 195,
            "fat_target_g": 60,
            "rationale": "参考你填写的静息能量与活动系数，以温和缺口支持减脂，保留足够能量用于训练。",
            "assumptions": [
                "使用最近记录的体重；未记录的运动不额外推测。",
                "没有年龄、健康状况与目标期限，建议作为一般成年健身人群的初始参考。",
            ],
        }, {"total_tokens": 0}

    def meal(self, config, path, note):
        return {
            "items": [
                {
                    "name": "鸡蛋蛋白",
                    "consumed_part": "3 个蛋清，不吃蛋黄",
                    "estimated_edible_grams": 100,
                    "kcal": 52,
                    "protein_g": 11,
                    "carbs_g": 0.7,
                    "fat_g": 0.2,
                },
                {
                    "name": "鸡胸肉",
                    "consumed_part": "熟制可食部分",
                    "estimated_edible_grams": 150,
                    "kcal": 248,
                    "protein_g": 46,
                    "carbs_g": 0,
                    "fat_g": 5,
                },
            ],
            "assumptions": ["测试接口；份量需要人工确认", note],
            "total_kcal": 300,
        }, {"total_tokens": 0}

    def meal_description(self, config, description, note="", path=None):
        return {
            "items": [
                {
                    "name": "板烧鸡腿堡",
                    "consumed_part": "去除酱料，按一份估算",
                    "estimated_edible_grams": 180,
                    "kcal": 420,
                    "protein_g": 25,
                    "carbs_g": 38,
                    "fat_g": 18,
                    "fiber_g": 2,
                    "sugar_g": 7,
                    "sodium_mg": 850,
                }
            ],
            "assumptions": ["测试 AI 估算；实际品牌配方和份量需要核对", description],
            "total_kcal": 420,
        }, {"total_tokens": 0}

    def feedback(self, config, context):
        return {
            "summary": "你已经完整记录了饮食和训练。把注意力放在长期趋势，继续保持稳定的节奏。",
            "positives": ["蛋白质记录完整", "完成计划中的训练"],
            "adjustments": ["根据实际食用量核对份量"],
            "next_day_advice": "明天安排一次轻松步行，继续记录晨起体重和三餐。",
        }, {"total_tokens": 0}


def main():
    checks = ROOT / "artifacts" / "browser"
    checks.mkdir(parents=True, exist_ok=True)
    with nullcontext(tempfile.mkdtemp(prefix="run-", dir=checks)) as directory:
        temp = Path(directory)
        paths = RuntimePaths.initialize(temp)
        paths.configure_process()
        artifacts = paths.root / "caches" / "screenshots"
        artifacts.mkdir()
        store = WorkspaceHub(paths)
        vault = CredentialStore(store.control, paths)
        offline = OfflineAI()
        app = create_app(store, vault, ai=offline)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=1))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.05)
        errors = []
        console_errors = []
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(paths.root / "caches/browser-profile"),
                    downloads_path=str(paths.root / "tmp/downloads"),
                    channel="msedge",
                    headless=True,
                    viewport={"width": 1440, "height": 1050},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    reduced_motion="reduce",
                )
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                expected_version_error = False
                page.on(
                    "console",
                    lambda message: (
                        console_errors.append(message.text)
                        if message.type == "error"
                        and not (
                            "401" in message.text and "/api/me" in message.location.get("url", "")
                        )
                        and not (
                            expected_version_error
                            and "/api/version" in message.location.get("url", "")
                        )
                        else None
                    ),
                )
                page.goto(f"http://127.0.0.1:{port}")
                page.wait_for_timeout(1000)
                page.screenshot(path=str(artifacts / "initial.png"), full_page=True)
                page.get_by_role("button", name="创建账号", exact=True).click()
                page.get_by_label("用户名", exact=True).fill("browser-alice")
                page.get_by_label("密码", exact=True).fill("browser-password-123")
                page.get_by_role("button", name="创建账号", exact=True).click()
                page.get_by_label("API Key", exact=True).wait_for()
                assert page.get_by_label("API Key", exact=True).get_attribute("type") == "password"
                assert not page.request.get(f"http://127.0.0.1:{port}/api/me").json()["ai"][
                    "api_key_set"
                ]
                page.get_by_label("API Key", exact=True).fill("offline-alice-key")
                page.get_by_role("button", name="保存 AI 配置", exact=True).click()
                page.get_by_text("AI 配置已保存", exact=True).wait_for()
                assert page.get_by_label("API Key", exact=True).input_value() == ""
                assert "offline-alice-key" not in page.locator("body").inner_text()
                page.get_by_label("身高", exact=True).fill("175")
                page.get_by_label("初始体重", exact=True).fill("75")
                page.get_by_label("平均静息能量", exact=True).fill("1800")
                page.get_by_label("每日热量目标", exact=True).fill("2000")
                page.get_by_label("目标体重", exact=True).fill("65")
                page.get_by_role("button", name="AI 生成目标", exact=True).click()
                page.get_by_role("button", name="采用这组目标", exact=True).wait_for()
                # Generating alone does not overwrite fields or persist a profile.
                assert page.get_by_label("每日热量目标", exact=True).input_value() == "2000"
                assert page.request.get(f"http://127.0.0.1:{port}/api/me").json()["profile"] is None
                page.get_by_label("目标体重", exact=True).fill("64")
                assert page.get_by_role("button", name="采用这组目标", exact=True).is_disabled()
                page.get_by_label("目标体重", exact=True).fill("65")
                page.get_by_role("button", name="采用这组目标", exact=True).click()
                page.get_by_text("AI 建议已填入，可修改后保存", exact=True).wait_for()
                assert page.get_by_label("每日热量目标", exact=True).input_value() == "1800"
                assert page.get_by_label("蛋白质目标", exact=True).input_value() == "120"
                assert page.get_by_label("碳水目标", exact=True).input_value() == "195"
                assert page.get_by_label("脂肪目标", exact=True).input_value() == "60"
                page.screenshot(
                    path=str(artifacts / "settings-ai-goals-desktop.png"), full_page=True
                )
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(300)
                page.wait_for_timeout(300)
                page.screenshot(
                    path=str(artifacts / "settings-ai-goals-mobile.png"), full_page=True
                )
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                    "Goal card horizontal overflow: "
                    + json.dumps(
                        page.evaluate("""() =>
                    Array.from(document.querySelectorAll('main *')).filter(el => {
                      const rect = el.getBoundingClientRect(); return rect.right > innerWidth;
                    }).slice(0, 12).map(el => [el.tagName, el.className, el.getBoundingClientRect().width])
                    """)
                    )
                )
                page.set_viewport_size({"width": 1440, "height": 1050})
                page.get_by_role("button", name="保存资料与目标", exact=True).click()
                page.get_by_text("资料与目标已保存", exact=True).wait_for()
                page.reload()
                page.get_by_role("button", name="个人设置", exact=True).click()
                page.get_by_label("每日热量目标", exact=True).wait_for()
                assert page.get_by_label("蛋白质目标", exact=True).input_value() == "120"
                page.get_by_role("button", name="已填入目标", exact=True).wait_for()
                page.get_by_role("button", name="创建备份", exact=True).click()
                page.get_by_text("创建备份 · 已完成", exact=True).wait_for()
                page.get_by_label("个人数据目录", exact=True).fill("personal/browser-alice")
                page.once("dialog", lambda dialog: dialog.accept())
                page.get_by_role("button", name="复制迁移", exact=False).click()
                page.get_by_text("迁移个人目录 · 已完成", exact=True).wait_for()
                storage = page.request.get(f"http://127.0.0.1:{port}/api/storage").json()
                assert storage["workspace_relative"] == "personal/browser-alice"
                assert len(storage["archives"]) == 1
                page.screenshot(path=str(artifacts / "storage-desktop.png"), full_page=True)
                page.get_by_role("button", name="身体记录", exact=True).click()
                page.get_by_label("每日体重", exact=True).fill("74.8")
                page.get_by_role("button", name="保存身体记录", exact=True).click()
                page.get_by_text("身体数据已保存", exact=True).wait_for()
                page.get_by_role("navigation").get_by_role(
                    "button", name="饮食记录", exact=True
                ).click()
                image = io.BytesIO()
                Image.new("RGB", (320, 240), "#ebc175").save(image, "JPEG")
                with page.expect_file_chooser() as chooser:
                    page.get_by_role(
                        "button", name="上传餐食照片，支持拖入图片", exact=True
                    ).click()
                chooser.value.set_files(
                    {"name": "meal.jpg", "mimeType": "image/jpeg", "buffer": image.getvalue()}
                )
                page.get_by_text("照片已上传，可以补充食用说明", exact=True).wait_for()
                preview = page.get_by_role("img", name="已上传的餐食照片", exact=True)
                previous_image = preview.get_attribute("src")
                for files, message in [
                    (
                        [
                            {
                                "name": "note.txt",
                                "type": "text/plain",
                                "data": base64.b64encode(b"not an image").decode(),
                            }
                        ],
                        "请选择 JPEG、PNG、WebP 或 GIF 图片",
                    ),
                    (
                        [
                            {"name": "first.jpg", "type": "image/jpeg", "data": ""},
                            {"name": "second.jpg", "type": "image/jpeg", "data": ""},
                        ],
                        "每次请拖入一张餐食图片",
                    ),
                ]:
                    transfer = photo_transfer(page, files)
                    try:
                        page.locator(".upload-area").dispatch_event(
                            "drop", {"dataTransfer": transfer}
                        )
                        page.get_by_text(message, exact=True).wait_for()
                        assert preview.get_attribute("src") == previous_image
                    finally:
                        transfer.dispose()
                dropped = io.BytesIO()
                portrait = Image.new("RGB", (300, 400), "#54755f")
                draw = ImageDraw.Draw(portrait)
                draw.rectangle((0, 0, 60, 60), fill="red")
                draw.rectangle((240, 0, 299, 60), fill="green")
                draw.rectangle((0, 340, 60, 399), fill="blue")
                draw.rectangle((240, 340, 299, 399), fill="yellow")
                portrait.save(dropped, "PNG")
                transfer = photo_transfer(
                    page,
                    [
                        {
                            "name": "dropped.PNG",
                            "type": "",
                            "data": base64.b64encode(dropped.getvalue()).decode(),
                        }
                    ],
                )
                try:
                    page.locator(".upload-area").dispatch_event(
                        "dragenter", {"dataTransfer": transfer}
                    )
                    page.locator(".upload-area").dispatch_event(
                        "dragover", {"dataTransfer": transfer}
                    )
                    page.get_by_text("松开鼠标，上传这张照片", exact=True).wait_for()
                    page.screenshot(path=str(artifacts / "meal-dragging.png"), full_page=True)
                    page.locator(".upload-area").dispatch_event("drop", {"dataTransfer": transfer})
                    page.wait_for_function(
                        "previous => document.querySelector('.upload-area img')?.getAttribute('src') !== previous",
                        arg=previous_image,
                    )
                    page.get_by_text("照片已上传，可以补充食用说明", exact=True).wait_for()
                    assert page.locator(".upload-area.dragging").count() == 0
                    # An accidental file drop elsewhere must not navigate away from FitTrack.
                    page.locator("h2").dispatch_event("drop", {"dataTransfer": transfer})
                    page.get_by_text("请把图片拖到“餐食照片”的上传区域", exact=True).wait_for()
                    assert page.locator(".upload-area img").count() == 1
                finally:
                    transfer.dispose()
                page.wait_for_function("""() => {
                    const photo = document.querySelector('.upload-area img');
                    return photo?.naturalWidth === 300 && photo?.naturalHeight === 400;
                }""")
                assert (
                    preview.evaluate("element => getComputedStyle(element).objectFit") == "contain"
                )
                page.get_by_text("完整画面 · 300 × 400 px", exact=True).wait_for()
                assert (
                    page.request.get(
                        f"http://127.0.0.1:{port}{preview.get_attribute('src')}"
                    ).body()
                    == dropped.getvalue()
                )
                page.get_by_role("button", name="查看完整照片", exact=True).click()
                original = page.get_by_role("img", name="完整餐食原图", exact=True)
                original.wait_for()
                assert original.get_attribute("src") == preview.get_attribute("src")
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_function("document.documentElement.scrollWidth <= innerWidth")
                bounds = original.bounding_box()
                assert abs(bounds["width"] / bounds["height"] - 0.75) < 0.01
                page.get_by_role("dialog", name="完整餐食照片", exact=True).screenshot(
                    path=str(artifacts / "meal-full-preview-mobile.png")
                )
                page.get_by_role("button", name="关闭弹窗", exact=True).click()
                page.set_viewport_size({"width": 1440, "height": 1050})
                page.locator(".meal-upload-grid").screenshot(
                    path=str(artifacts / "meal-uncropped-preview.png")
                )
                page.get_by_role("button", name="鸡蛋只吃蛋白", exact=True).click()
                page.get_by_role("button", name="开始估算热量", exact=True).click()
                page.get_by_role("button", name="查看并确认草稿", exact=True).click()
                page.get_by_label("食用重量", exact=True).first.fill("200")
                page.get_by_label("食物热量", exact=True).first.input_value(timeout=5000)
                assert float(page.get_by_label("食物热量", exact=True).first.input_value()) == 104
                page.get_by_role("button", name="确认并计入当天", exact=True).click()
                page.get_by_text("餐食已确认入账", exact=True).wait_for()
                page.get_by_role("button", name="查看已入账餐食原图", exact=True).click()
                page.get_by_role("img", name="完整餐食原图", exact=True).wait_for()
                assert page.get_by_role("img", name="完整餐食原图", exact=True).get_attribute(
                    "src"
                ) == preview.get_attribute("src")
                page.get_by_role("button", name="关闭弹窗", exact=True).click()
                page.get_by_role("button", name="包装营养标签", exact=True).click()
                page.get_by_label("补充说明", exact=True).fill("每袋60克，实际吃了2袋")
                page.get_by_role("button", name="开始读取标签", exact=True).click()
                page.get_by_role("button", name="查看并确认草稿", exact=True).click()
                assert page.get_by_label("标签脂肪", exact=True).input_value() == ""
                assert page.get_by_role(
                    "button", name="确认标签并计入当天", exact=True
                ).is_disabled()
                page.get_by_label("标签脂肪", exact=True).fill("1.1")
                page.get_by_label("标签份量方式", exact=True).select_option("packs")
                page.get_by_label("标签每袋重量", exact=True).fill("60")
                page.get_by_label("标签实际袋数", exact=True).fill("2")
                page.get_by_role("button", name="计算实际摄入", exact=True).click()
                page.get_by_label("标签摄入预览", exact=True).get_by_text(
                    "107.27 kcal", exact=True
                ).wait_for()
                page.get_by_label("标签实际袋数", exact=True).fill("0.5")
                assert page.get_by_role(
                    "button", name="确认标签并计入当天", exact=True
                ).is_disabled()
                page.get_by_role("button", name="计算实际摄入", exact=True).click()
                page.get_by_label("标签摄入预览", exact=True).get_by_text(
                    "26.82 kcal", exact=True
                ).wait_for()
                page.get_by_label("标签实际袋数", exact=True).fill("2")
                page.get_by_role("button", name="计算实际摄入", exact=True).click()
                page.get_by_label("标签摄入预览", exact=True).get_by_text(
                    "107.27 kcal", exact=True
                ).wait_for()
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_function("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(artifacts / "nutrition-label-mobile.png"), full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1050})
                page.get_by_role("button", name="确认标签并计入当天", exact=True).click()
                page.get_by_text("标签餐食已确认入账", exact=True).wait_for()
                assert (
                    page.request.get(f"http://127.0.0.1:{port}/api/days/{today()}").json()[
                        "totals"
                    ]["kcal"]
                    == 459.27
                )
                page.get_by_role("region", name="每周饮食记录", exact=True).screenshot(
                    path=str(artifacts / "diet-week-desktop.png")
                )
                page.get_by_role("button", name="普通餐食照片", exact=True).click()
                page.get_by_role("button", name="饮食上一周", exact=True).click()
                previous_day = page.get_by_role("article", name="2026-10-14饮食记录", exact=True)
                previous_day.get_by_role("button", name="补记本日饮食", exact=True).click()
                page.get_by_role("button", name="精确录入", exact=True).click()
                page.get_by_label("餐食描述", exact=True).fill("历史补录测试餐")
                page.get_by_label("整餐蛋白质", exact=True).fill("10")
                page.get_by_label("整餐碳水", exact=True).fill("10")
                page.get_by_label("整餐脂肪", exact=True).fill("4")
                assert page.get_by_text("116 kcal", exact=True).count() >= 1
                page.get_by_role("button", name="确认并计入当天", exact=True).click()
                previous_day.get_by_text("历史补录测试餐", exact=True).wait_for()
                exact_day = page.request.get(
                    f"http://127.0.0.1:{port}/api/days/2026-10-14"
                ).json()
                assert exact_day["totals"]["kcal"] == 116
                assert exact_day["meals"][0]["nutrition_mode"] == "precise"
                page.get_by_role("button", name="今天", exact=True).click()
                page.get_by_role("article", name="2026-10-15饮食记录", exact=True).get_by_text(
                    "鸡胸肉丸", exact=True
                ).wait_for()
                page.get_by_role("button", name="手动记一餐", exact=True).click()
                page.get_by_label("餐食描述", exact=True).fill(
                    "麦当劳板烧鸡腿堡 1 个，去除酱料"
                )
                page.get_by_role("button", name="生成 AI 营养草稿", exact=True).click()
                page.get_by_label("食物名称", exact=True).fill("麦当劳板烧鸡腿堡")
                page.get_by_role("button", name="精确录入", exact=True).click()
                page.get_by_label("整餐蛋白质", exact=True).fill("25")
                page.get_by_label("整餐碳水", exact=True).fill("38")
                page.get_by_label("整餐脂肪", exact=True).fill("18")
                page.get_by_role("button", name="AI 估算", exact=True).click()
                assert page.get_by_label("食物名称", exact=True).first.input_value() == "麦当劳板烧鸡腿堡"
                page.get_by_role("button", name="精确录入", exact=True).click()
                assert page.get_by_label("整餐蛋白质", exact=True).input_value() == ""
                assert page.get_by_label("整餐碳水", exact=True).input_value() == ""
                assert page.get_by_label("整餐脂肪", exact=True).input_value() == ""
                page.get_by_label("整餐蛋白质", exact=True).fill("25")
                page.get_by_label("整餐碳水", exact=True).fill("38")
                page.get_by_label("整餐脂肪", exact=True).fill("18")
                assert page.get_by_text("414 kcal", exact=True).count() >= 1
                page.get_by_role("button", name="确认并计入当天", exact=True).click()
                page.get_by_text("餐食已确认入账", exact=True).wait_for()
                precise_day = page.request.get(
                    f"http://127.0.0.1:{port}/api/days/{today()}"
                ).json()
                precise = next(
                    meal for meal in precise_day["meals"] if meal["nutrition_mode"] == "precise"
                )
                assert precise["items"][0]["kcal"] == 414
                assert precise["source_job_id"] is None
                assert precise["assumptions"] == []
                precise_card = page.locator(".meal-card").filter(
                    has_text="麦当劳板烧鸡腿堡 1 个，去除酱料"
                )
                precise_card.get_by_role("button", name="编辑餐食", exact=True).click()
                assert page.get_by_label("整餐蛋白质", exact=True).input_value() == "25"
                assert page.get_by_label("整餐碳水", exact=True).input_value() == "38"
                assert page.get_by_label("整餐脂肪", exact=True).input_value() == "18"
                page.get_by_role("button", name="关闭弹窗", exact=True).click()
                page.get_by_role("button", name="删除餐食", exact=True).last.click()
                page.get_by_role("button", name="确认删除", exact=True).click()
                page.get_by_text("餐食记录已删除", exact=True).wait_for()
                page.get_by_role("button", name="手动记一餐", exact=True).click()
                page.get_by_label("餐食描述", exact=True).fill(
                    "麦当劳板烧鸡腿堡 1 个，去除酱料"
                )
                page.get_by_role("button", name="生成 AI 营养草稿", exact=True).click()
                page.get_by_label("食物名称", exact=True).fill("麦当劳板烧鸡腿堡")
                page.get_by_role("button", name="确认并计入当天", exact=True).click()
                page.get_by_text("餐食已确认入账", exact=True).wait_for()
                estimated_day = page.request.get(
                    f"http://127.0.0.1:{port}/api/days/{today()}"
                ).json()
                assert any(
                    meal["nutrition_mode"] == "estimate"
                    and meal["meal_description"] == "麦当劳板烧鸡腿堡 1 个，去除酱料"
                    for meal in estimated_day["meals"]
                )
                page.get_by_role("button", name="删除餐食", exact=True).last.click()
                page.get_by_role("button", name="确认删除", exact=True).click()
                page.get_by_text("餐食记录已删除", exact=True).wait_for()
                page.get_by_role("button", name="训练与排期", exact=True).click()
                page.get_by_role("button", name="添加排期", exact=True).click()
                page.get_by_label("排期名称", exact=True).fill("上肢力量训练")
                page.get_by_role("button", name="保存排期", exact=True).click()
                page.get_by_text("训练排期已保存", exact=True).wait_for()
                page.get_by_role("button", name="记录此次训练", exact=True).click()
                page.get_by_role("button", name="添加动作", exact=True).click()
                page.get_by_label("动作名称", exact=True).fill("卧推")
                page.get_by_label("总外加重量 / kg", exact=True).fill("60")
                page.get_by_label("次数", exact=True).fill("10")
                assert not page.get_by_role("button", name="AI 估算消耗", exact=True).count()
                page.get_by_role("button", name="保存训练", exact=True).click()
                page.get_by_text("训练已记录", exact=True).wait_for()

                # Applying a reactive template must clone its exercises into a
                # day-local draft without changing the source template.
                builtin = page.get_by_role("button", name="套用到今天", exact=True).first
                builtin.click()
                page.get_by_label("训练名称", exact=True).fill("预置模板当天副本")
                page.get_by_label("动作名称", exact=True).first.fill("当天临时动作")
                page.get_by_role("button", name="关闭弹窗", exact=True).click()
                builtin.click()
                assert page.get_by_label("动作名称", exact=True).first.input_value() == "高位下拉"
                page.get_by_role("button", name="关闭弹窗", exact=True).click()

                page.get_by_role("button", name="新建个人模板", exact=True).click()
                page.get_by_label("模板名称", exact=True).fill("个人卧推模板")
                page.get_by_label("动作名称", exact=True).fill("杠铃卧推")
                page.get_by_role("button", name="保存模板", exact=True).click()
                page.get_by_text("训练模板已保存", exact=True).wait_for()
                personal_template = page.get_by_role("article").filter(
                    has_text="个人卧推模板"
                )
                personal_template.get_by_role("button", name="套用到今天", exact=True).click()
                page.get_by_label("训练名称", exact=True).fill("模板训练当天记录")
                page.get_by_label("动作名称", exact=True).first.fill("当天卧推变式")
                page.get_by_role("button", name="保存训练", exact=True).click()
                page.get_by_text("训练已记录", exact=True).wait_for()
                personal_template.get_by_role("button", name="编辑模板", exact=True).click()
                assert page.get_by_label("动作名称", exact=True).input_value() == "杠铃卧推"
                page.get_by_role("button", name="关闭弹窗", exact=True).click()
                with page.expect_download() as template_download:
                    page.get_by_role("button", name="导出模板 JSON", exact=True).click()
                exported_templates = json.loads(
                    Path(template_download.value.path()).read_text(encoding="utf-8")
                )
                assert exported_templates["format"] == "fittrack-training"
                assert exported_templates["templates"][0]["title"] == "个人卧推模板"
                personal_template.get_by_role("button", name="导出二维码", exact=True).click()
                page.get_by_role("img", name="训练模板二维码", exact=True).wait_for()
                page.evaluate(
                    """async () => {
                      const image = document.querySelector('.qr-export img');
                      const input = document.querySelector('input[accept="image/*"]');
                      const blob = await (await fetch(image.src)).blob();
                      const transfer = new DataTransfer();
                      transfer.items.add(new File([blob], 'template.png', {type: 'image/png'}));
                      input.files = transfer.files;
                      input.dispatchEvent(new Event('change', {bubbles: true}));
                    }"""
                )
                page.get_by_text("训练模板已导入", exact=True).wait_for()
                imported = page.request.get(
                    f"http://127.0.0.1:{port}/api/workout-templates"
                ).json()
                assert sum(item["title"] == "个人卧推模板" for item in imported) == 2
                workout_rows = page.request.get(
                    f"http://127.0.0.1:{port}/api/days/{today()}"
                ).json()["workouts"]
                assert any(
                    workout["title"] == "模板训练当天记录"
                    and workout["exercises"][0]["name"] == "当天卧推变式"
                    for workout in workout_rows
                )

                work_before = len(
                    page.request.get(f"http://127.0.0.1:{port}/api/days/{today()}").json()[
                        "workouts"
                    ]
                )
                page.get_by_role("button", name="记录训练", exact=True).click()
                page.get_by_label("训练名称", exact=True).fill("版本不匹配时保留表单")
                expected_version_error = True
                page.route(
                    "**/api/version",
                    lambda route: route.fulfill(status=404, json={"detail": "Not Found"}),
                )
                page.get_by_role("button", name="保存训练", exact=True).click()
                page.locator(".version-alert").wait_for()
                assert (
                    page.get_by_label("训练名称", exact=True).input_value()
                    == "版本不匹配时保留表单"
                )
                assert (
                    len(
                        page.request.get(f"http://127.0.0.1:{port}/api/days/{today()}").json()[
                            "workouts"
                        ]
                    )
                    == work_before
                )
                page.unroute("**/api/version")
                page.get_by_role("button", name="关闭弹窗", exact=True).click()
                page.get_by_role("button", name="重新检查版本", exact=True).click()
                page.wait_for_function("!document.querySelector('.version-alert')")
                expected_version_error = False
                before_count = len(
                    page.request.get(f"http://127.0.0.1:{port}/api/days/{today()}").json()[
                        "workouts"
                    ]
                )
                page.get_by_role("button", name="记录训练", exact=True).click()
                page.get_by_label("训练类别", exact=True).select_option("cardio")
                page.get_by_label("运动类型", exact=True).select_option("badminton")
                page.get_by_label("训练名称", exact=True).fill("休闲羽毛球")
                page.get_by_label(re.compile("^实际时长")).fill("60")
                page.get_by_label(re.compile("^运动净消耗覆盖")).fill("123")
                description = "中间休息较多，实际打球约40分钟"
                page.get_by_label("自定义运动描述", exact=True).fill(description)
                page.get_by_role("button", name="AI 估算消耗", exact=True).click()
                page.get_by_role("button", name="采用估算", exact=True).wait_for()
                assert (
                    len(
                        page.request.get(f"http://127.0.0.1:{port}/api/days/{today()}").json()[
                            "workouts"
                        ]
                    )
                    == before_count
                )
                page.get_by_label("自定义运动描述", exact=True).fill("改为全程高强度")
                assert page.get_by_role("button", name="采用估算", exact=True).is_disabled()
                page.get_by_label("自定义运动描述", exact=True).fill(description)
                page.get_by_role("button", name="采用估算", exact=True).click()
                page.get_by_role("button", name="已采用估算", exact=True).wait_for()
                assert page.get_by_label(re.compile("^手动 MET")).input_value() == "6"
                assert page.get_by_label(re.compile("^运动净消耗覆盖")).input_value() == ""
                page.screenshot(path=str(artifacts / "cardio-ai-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_function("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(artifacts / "cardio-ai-mobile.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                    json.dumps(
                        page.evaluate(
                            """() => [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth).slice(0, 15).map(el => [el.tagName, el.className, el.getBoundingClientRect().width, el.textContent.slice(0,80)])"""
                        ),
                        ensure_ascii=False,
                    )
                )
                page.set_viewport_size({"width": 1440, "height": 1050})
                page.get_by_role("button", name="保存训练", exact=True).click()
                page.get_by_text("训练已记录", exact=True).wait_for()
                cardio = page.request.get(f"http://127.0.0.1:{port}/api/days/{today()}").json()[
                    "workouts"
                ][-1]
                assert cardio["ai_estimate_job_id"] and cardio["energy"]["net_kcal"] == 373.8
                page.get_by_role("button", name="编辑训练", exact=True).last.click()
                page.get_by_role("button", name="已采用估算", exact=True).wait_for()
                assert page.get_by_label("自定义运动描述", exact=True).input_value() == description
                page.get_by_role("button", name="关闭弹窗", exact=True).click()
                page.get_by_role("button", name="今日概览", exact=True).click()
                weekly_panel = page.get_by_role("region", name="每周 AI 复盘", exact=True)
                weekly_panel.get_by_text("完整记录 0/7 天", exact=True).wait_for()
                assert weekly_panel.get_by_role(
                    "button", name="生成本周分析", exact=True
                ).is_disabled()
                page.get_by_role("button", name="仅完成今日记录", exact=True).click()
                weekly_panel.get_by_text("完整记录 1/7 天", exact=True).wait_for()
                page.get_by_role("button", name="完成今日记录并生成建议", exact=True).click()
                page.get_by_text(
                    "你已经完整记录了饮食和训练。把注意力放在长期趋势，继续保持稳定的节奏。",
                    exact=True,
                ).wait_for()
                # Seed only this disposable QA account, to inspect populated trend charts.
                user_id = store.rows("SELECT id FROM users WHERE username='browser-alice'")[0]["id"]
                from datetime import date, timedelta

                for offset in range(1, 14):
                    day = (date.fromisoformat(today()) - timedelta(days=offset)).isoformat()
                    store.save_body(
                        user_id,
                        {
                            "date": day,
                            "weight_kg": round(
                                74.8 + offset * 0.09 + (0.12 if offset % 3 == 0 else 0), 1
                            ),
                            "body_fat_pct": round(20 + offset * 0.06, 1),
                            "resting_kcal": None,
                            "note": "浏览器测试数据",
                        },
                    )
                page.reload()
                page.get_by_text("把改变，交给每天。", exact=True).wait_for()
                page.wait_for_timeout(500)
                page.screenshot(path=str(artifacts / "dashboard-desktop.png"), full_page=True)
                page.get_by_role("button", name="趋势分析", exact=True).click()
                page.get_by_label("趋势统计范围").wait_for()
                assert "2026-10-15" in page.get_by_label("趋势统计范围").inner_text()
                # The analysis page has one fixed start, including after the old 30-day window
                # and across the backend's 366-date request boundary.
                for selected, expected_days in [("2026-11-20", 37), ("2027-10-16", 367)]:
                    page.get_by_label("记录日期", exact=True).fill(selected)
                    page.get_by_label("记录日期", exact=True).dispatch_event("change")
                    page.wait_for_function(
                        """({end, count}) => {
                      const cells = [...document.querySelectorAll('tbody tr td:first-child')];
                      return cells.length === count && cells[0].textContent === end
                        && cells.at(-1).textContent === '2026-10-15';
                    }""",
                        arg={"end": selected, "count": expected_days},
                    )
                page.get_by_label("记录日期", exact=True).fill("2026-10-14")
                page.get_by_label("记录日期", exact=True).dispatch_event("change")
                page.get_by_text(
                    "趋势统计从 2026-10-15 开始，请选择该日期或之后的日期。", exact=True
                ).wait_for()
                assert page.get_by_text("此范围暂无趋势数据", exact=True).is_visible()
                assert page.request.get(
                    f"http://127.0.0.1:{port}/api/body?start=2026-10-14&end=2026-10-14"
                ).json(), "Pre-start measurements must remain stored"
                page.get_by_role("button", name="今天", exact=True).click()
                page.wait_for_function("""() => {
                  const cells = [...document.querySelectorAll('tbody tr td:first-child')];
                  return cells.length > 0 && cells.at(-1).textContent === '2026-10-15';
                }""")
                page.wait_for_timeout(500)
                page.screenshot(path=str(artifacts / "trends-desktop.png"), full_page=True)
                for label in ["身体记录", "饮食记录", "训练与排期", "个人设置"]:
                    page.get_by_role("navigation").get_by_role(
                        "button", name=label, exact=True
                    ).click()
                    assert page.locator("main").count() == 1
                page.get_by_role("button", name="今日概览", exact=True).click()
                # Test time travel only inside this disposable server, never in production.
                for offset in range(1, 7):
                    day = (date(2026, 10, 15) + timedelta(days=offset)).isoformat()
                    store.save_entry(
                        user_id,
                        "meal",
                        {
                            "date": day,
                            "slot": "dinner",
                            "note": "浏览器周复盘测试",
                            "items": [
                                {
                                    "name": "测试餐",
                                    "estimated_edible_grams": 300,
                                    "kcal": 1800,
                                    "protein_g": 120,
                                    "carbs_g": 195,
                                    "fat_g": 60,
                                }
                            ],
                        },
                    )
                    store.complete_day(user_id, day)
                with (
                    patch("fittrack.calculations.today", return_value="2026-10-22"),
                    patch("fittrack.routes.today", return_value="2026-10-22"),
                ):
                    page.reload()
                    weekly_panel.get_by_text("完整记录 7/7 天", exact=True).wait_for()
                    weekly_panel.get_by_role("button", name="生成本周分析", exact=True).click()
                    weekly_panel.get_by_text(
                        "这一周已完成七天记录，饮食与训练都有迹可循。", exact=True
                    ).wait_for()
                    assert offline.weekly_calls == 1
                    page.screenshot(
                        path=str(artifacts / "weekly-review-desktop.png"), full_page=True
                    )
                    weekly_panel.screenshot(path=str(artifacts / "weekly-card-desktop.png"))
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_function("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(
                        path=str(artifacts / "weekly-review-mobile.png"), full_page=True
                    )
                    weekly_panel.screenshot(path=str(artifacts / "weekly-card-mobile.png"))
                    page.set_viewport_size({"width": 1440, "height": 1050})
                    page.get_by_label("周复盘周期", exact=True).select_option("2026-10-22")
                    weekly_panel.get_by_text(re.compile("最早 2026-10-29 可生成")).wait_for()
                    assert weekly_panel.get_by_role(
                        "button", name="生成本周分析", exact=True
                    ).is_disabled()
                    page.get_by_label("周复盘周期", exact=True).select_option("2026-10-15")
                    weekly_panel.get_by_text(
                        "这一周已完成七天记录，饮食与训练都有迹可循。", exact=True
                    ).wait_for()
                    assert offline.weekly_calls == 1
                    store.save_body(user_id, {"date": "2026-10-16", "weight_kg": 74.7})
                    page.reload()
                    weekly_panel.get_by_text(
                        "本周记录已变化，下面保留生成时的报告与统计，可手动重新分析。", exact=True
                    ).wait_for()
                page.reload()
                page.get_by_text("把改变，交给每天。", exact=True).wait_for()
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(300)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                    "Mobile horizontal overflow"
                )
                page.screenshot(path=str(artifacts / "dashboard-mobile.png"), full_page=True)
                page.get_by_role("button", name="打开导航", exact=True).click()
                page.get_by_role("navigation").get_by_role(
                    "button", name="饮食记录", exact=True
                ).click()
                page.get_by_role("button", name="手动记一餐", exact=True).click()
                assert page.get_by_role("dialog").is_visible()
                page.get_by_role("button", name="关闭弹窗", exact=True).click()
                page.set_viewport_size({"width": 1440, "height": 1050})
                page.get_by_role("button", name="退出登录", exact=True).click()
                page.get_by_text("欢迎回来", exact=True).wait_for()
                assert "上肢力量训练" not in page.locator("body").inner_text()
                page.get_by_role("button", name="创建账号", exact=True).click()
                page.get_by_label("用户名", exact=True).fill("browser-bob")
                page.get_by_label("密码", exact=True).fill("browser-password-456")
                page.get_by_role("button", name="创建账号", exact=True).click()
                page.get_by_label("初始体重", exact=True).wait_for()
                assert page.get_by_label("初始体重", exact=True).input_value() == ""
                bob_day = page.request.get(f"http://127.0.0.1:{port}/api/days/{today()}").json()
                assert not bob_day["meals"] and not bob_day["workouts"]
                assert bob_day["feedback"] is None
                assert page.get_by_role("button", name="保存 AI 配置", exact=True).count() == 1
                assert not page.request.get(f"http://127.0.0.1:{port}/api/me").json()["ai"][
                    "api_key_set"
                ]
                assert not page.get_by_role("button", name="停止本机服务", exact=True).count()
                page.get_by_label("API Key", exact=True).fill("offline-bob-session-key")
                page.get_by_label("记住此账号的 Key", exact=True).uncheck()
                page.get_by_role("button", name="保存 AI 配置", exact=True).click()
                page.get_by_text("AI 配置已保存", exact=True).wait_for()
                assert (
                    page.request.get(f"http://127.0.0.1:{port}/api/me").json()["ai"][
                        "credential_scope"
                    ]
                    == "session"
                )
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(artifacts / "storage-mobile.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                    json.dumps(
                        page.evaluate(
                            """() => Array.from(document.querySelectorAll('main *')).filter(el=>el.getBoundingClientRect().right>innerWidth).slice(0,15).map(el=>[el.tagName,el.className,el.getBoundingClientRect().width,el.textContent.slice(0,60)])"""
                        ),
                        ensure_ascii=False,
                    )
                )
                page.set_viewport_size({"width": 1440, "height": 1050})
                page.get_by_role("button", name="退出登录", exact=True).click()
                page.get_by_text("欢迎回来", exact=True).wait_for()
                assert not vault._memory
                context.close()
                assert not errors, errors
                assert not console_errors, console_errors
                print(
                    json.dumps(
                        {
                            "browser": "Microsoft Edge headless",
                            "flows": [
                                "register",
                                "profile",
                                "AI goal generation and adoption",
                                "goal persistence and stale input",
                                "body",
                                "upload",
                                "photo drag and drop replacement with empty MIME type",
                                "invalid/multiple file drops and navigation prevention",
                                "portrait photo whole-frame preview, dimensions and original bytes",
                                "full-photo viewer on mobile and confirmed meals",
                                "label extraction with missing value, portion calculation and confirmation",
                                "historical diet week and pre-start backfill",
                                "backend version mismatch blocks save and preserves draft",
                                "AI draft",
                                "precise meal macro entry with server-calculated 4/4/9 calories",
                                "AI-to-precise reset, precise-meal edit values and confirmation without AI provenance",
                                "described-meal AI estimate and confirmation",
                                "portion scaling",
                                "confirm meal",
                                "plan",
                                "strength sets",
                                "template clone isolation, personal-template edit, JSON export, and QR image round-trip",
                                "badminton cardio AI preview, invalidation, adoption, save and reload",
                                "manual completion without daily AI",
                                "weekly eligibility, history, saved report and stale notice",
                                "weekly and cardio mobile layout",
                                "daily feedback",
                                "charts",
                                "analysis fixed start 2026-10-15 and historical-date empty state",
                                "analysis retains fixed start after 30 days and across years",
                                "mobile modal",
                                "logout",
                                "second-user isolation",
                                "per-account encrypted and session AI keys",
                                "backup and workspace migration",
                                "controlled paths and masked password input",
                            ],
                            "runtime_errors": errors,
                            "screenshots": str(artifacts),
                        },
                        ensure_ascii=False,
                    )
                )
        finally:
            app.state.bus.close()
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("QA server did not shut down")
            store.close()


if __name__ == "__main__":
    with (
        patch("fittrack.calculations.today", return_value=today()),
        patch("fittrack.routes.today", return_value=today()),
    ):
        main()
