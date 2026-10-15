"""Real browser + actual local HTTP service. No response mocking.

Run with the server started:
PLAYWRIGHT_BROWSERS_PATH=.../.browsers .venv/bin/python tests/browser_smoke.py
"""
from pathlib import Path
import json
import re
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "screenshots"
OUT.mkdir(exist_ok=True)
checks = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8787", wait_until="networkidle")
    expect(page.get_by_text("模拟环境已连接", exact=True)).to_be_visible()
    page.screenshot(path=str(OUT / "01_studio_desktop.png"), full_page=True)

    def command(text):
        page.get_by_role("textbox", name="给经纬助手发送指令").fill(text)
        with page.expect_response(lambda r: r.url.endswith("/api/studio/chat") and r.request.method == "POST") as pending:
            page.get_by_role("button", name="发送指令", exact=True).click()
        response = pending.value.json()
        expect(page.get_by_role("textbox", name="给经纬助手发送指令")).to_be_enabled() if response["status"] != "confirm" else None
        return response

    r = command("副驾车窗开50%")
    assert r["status"] == "executed" and r["vehicle"]["windows"]["front_right"] == 50
    assert r["vehicle"]["windows"]["rear_right"] == 0
    checks.append("target_window_changed_and_rear_unchanged")
    page.screenshot(path=str(OUT / "02_window_verified.png"), full_page=True)

    with page.expect_response(lambda r: r.url.endswith("/api/studio/reset")):
        page.get_by_role("button", name="重置车辆与对话", exact=True).click()
    r = command("帮我打开一点")
    assert r["status"] == "clarify" and all(x == 0 for x in r["vehicle"]["windows"].values())
    checks.append("ambiguity_no_action")
    r = command("打开后备箱")
    assert r["status"] == "confirm" and not r["vehicle"]["trunk_open"]
    with page.expect_response(lambda r: r.url.endswith("/api/studio/confirm")) as pending:
        page.get_by_role("button", name="确认执行", exact=False).click()
    r = pending.value.json()
    assert r["status"] == "executed" and r["vehicle"]["trunk_open"]
    checks.append("confirmation_commits_simulated_action")

    page.get_by_role("button", name=re.compile("可信实验室")).click()
    page.get_by_role("button", name="模拟环境", exact=True).click()
    page.get_by_label("模拟车速").fill("100")
    page.get_by_label("挡位", exact=False).select_option("D")
    with page.expect_response(lambda r: r.url.endswith("/api/studio/reset")):
        page.get_by_role("button", name="应用设置", exact=True).click()
    r = command("打开副驾车门")
    assert r["status"] == "blocked" and not any(r["vehicle"]["doors"].values())
    checks.append("driving_door_blocked")
    page.screenshot(path=str(OUT / "03_safety_lab.png"), full_page=True)

    page.get_by_role("button", name="模拟环境", exact=True).click()
    page.get_by_label("模拟车速").fill("0")
    page.get_by_label("挡位", exact=False).select_option("P")
    page.get_by_label("故障注入", exact=False).select_option("wrong_target")
    with page.expect_response(lambda r: r.url.endswith("/api/studio/reset")):
        page.get_by_role("button", name="应用设置", exact=True).click()
    r = command("副驾车窗开50%")
    assert r["status"] == "failed" and r["vehicle"]["windows"]["rear_right"] == 50
    assert r["vehicle"]["windows"]["front_right"] == 0
    checks.append("wrong_target_detected_not_false_success")
    page.screenshot(path=str(OUT / "04_wrong_target.png"), full_page=True)

    page.get_by_role("button", name="模拟环境", exact=True).click()
    page.get_by_label("故障注入", exact=False).select_option("none")
    page.get_by_label("车辆配置", exact=False).select_option("premium")
    with page.expect_response(lambda r: r.url.endswith("/api/studio/reset")):
        page.get_by_role("button", name="应用设置", exact=True).click()
    r = command("打开按摩")
    assert r["status"] == "executed" and r["vehicle"]["massage"]
    checks.append("premium_capability_enabled")
    page.get_by_role("button", name="模拟环境", exact=True).click()
    page.get_by_label("车辆配置", exact=False).select_option("standard")
    with page.expect_response(lambda r: r.url.endswith("/api/studio/reset")):
        page.get_by_role("button", name="应用设置", exact=True).click()
    r = command("打开按摩")
    assert r["status"] == "unsupported" and not r["vehicle"]["massage"]
    checks.append("standard_capability_absent")
    r = command("EC40 2026后向儿童座椅放副驾，应该怎么安装？")
    assert "child.rear_front" in r.get("fact_ids", []) and "关闭" in r["message"]
    checks.append("manual_conditional_warning_with_evidence")
    page.screenshot(path=str(OUT / "05_grounded_answer.png"), full_page=True)

    page.get_by_role("button", name=re.compile("车辆知识")).click()
    page.get_by_role("searchbox", name="搜索手册证据").fill("气囊")
    expect(page.get_by_text("副驾后向座椅与气囊", exact=True)).to_be_visible()
    checks.append("manual_search")
    page.screenshot(path=str(OUT / "06_manual_library.png"), full_page=True)
    page.get_by_role("button", name=re.compile("评测报告")).click()
    expect(page.get_by_role("heading", name="可信能力，经过实测。")).to_be_visible()
    checks.append("report_loaded")
    page.screenshot(path=str(OUT / "07_benchmark.png"), full_page=True)

    mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    mobile.on("pageerror", lambda e: errors.append(str(e)))
    mobile.goto("http://127.0.0.1:8787", wait_until="networkidle")
    assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    checks.append("390px_no_horizontal_overflow")
    mobile.screenshot(path=str(OUT / "08_studio_mobile.png"), full_page=True)
    assert not errors, errors
    browser.close()

report = {"passed": len(checks), "checks": checks, "page_errors": errors, "network": "real local API, no mocking", "voice": "browser UI only; no real microphone/audio device validation"}
(ROOT / "results" / "browser_checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
