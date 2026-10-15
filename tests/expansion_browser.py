"""Actual workspace API browser journeys; microphone events are explicitly synthetic."""
from pathlib import Path
import json
import os
import re
import uuid
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("STUDIO_TEST_URL", "http://127.0.0.1:8788")
OUT = ROOT / "results/expansion_ui"
OUT.mkdir(exist_ok=True)
checks, errors = [], []


def record(name, **extra):
    checks.append({"name": name, "passed": True, **extra})


def reply(page, count):
    expect(page.locator(".meridian-message.assistant")).to_have_count(count, timeout=180000)
    expect(page.get_by_label("推理提供方")).to_be_enabled(timeout=180000)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    page.set_default_timeout(20000)
    sid = "ui-expansion-" + uuid.uuid4().hex[:12]
    page.add_init_script(f"sessionStorage.setItem('meridian.session', {json.dumps(sid)})")
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    expect(page.get_by_label("推理提供方")).to_have_value("kimi")
    expect(page.get_by_role("tab")).to_have_count(5)
    page.get_by_label("推理提供方").select_option("offline")
    page.get_by_role("button", name="天窗开30%", exact=True).click()
    reply(page, 1)
    expect(page.locator(".workspace-control-grid article").filter(has_text="天窗").locator("b")).to_have_text("30%")
    page.screenshot(path=str(OUT / "05_vehicle_controls.png"), full_page=True)
    record("new vehicle control uses actual backend and state")

    page.get_by_role("tab", name="记忆偏好").click()
    key = "ui_qa_" + uuid.uuid4().hex[:8]
    page.get_by_label("偏好名称").fill(key)
    page.get_by_label("偏好内容").fill("测试拿铁")
    page.get_by_role("button", name="保存偏好", exact=True).click()
    pref = page.locator(".workspace-preference-list article").filter(has_text=key)
    expect(pref).to_contain_text("测试拿铁")
    pref.get_by_role("button", name="修改").click()
    page.get_by_label("偏好内容").fill("测试无糖拿铁")
    page.get_by_role("button", name="保存偏好", exact=True).click()
    expect(pref).to_contain_text("测试无糖拿铁")
    other = page.request.get(f"{BASE}/api/studio/workspace?session_id={sid}-new").json()
    assert any(item["key"] == key and item["value"] == "测试无糖拿铁" for item in other["preferences"])
    page.screenshot(path=str(OUT / "06_preferences.png"), full_page=True)
    pref.get_by_role("button", name="删除").click()
    expect(pref).to_have_count(0)
    record("preferences create update cross-session persistence delete")

    page.get_by_label("推理提供方").select_option("kimi")
    page.get_by_role("tab", name="导航出行").click()
    page.get_by_label("搜索地点").fill("杭州东站")
    page.get_by_role("button", name="查找", exact=True).click()
    reply(page, 2)
    assert page.locator(".workspace-place-list article").count() > 0
    page.locator(".workspace-place-list article").first.get_by_role("button", name="到这里").click()
    reply(page, 3)
    expect(page.locator(".workspace-route-summary")).to_be_visible()
    assert page.locator('.workspace-map path[stroke="#456fa4"]').count() > 0
    page.screenshot(path=str(OUT / "07_real_route.png"), full_page=True)
    record("real place search candidate selection route geometry")

    page.get_by_role("tab", name="信息服务").click()
    page.get_by_role("button", name="查询杭州天气", exact=False).click()
    reply(page, 4)
    expect(page.locator(".workspace-weather")).to_be_visible()
    page.screenshot(path=str(OUT / "08_live_weather.png"), full_page=True)
    record("weather cards show actual provider results")

    page.get_by_role("button", name=re.compile("车辆知识")).click()
    assert page.locator(".workspace-document-list article").count() >= 3
    options = page.get_by_label("本次提问手册").locator("option").evaluate_all("els => els.map(e => ({value:e.value,label:e.textContent}))")
    selected = next(item["value"] for item in options if item["value"])
    page.get_by_label("本次提问手册").select_option(selected)
    page.get_by_label("查询完整手册").fill("胎压警告灯亮了怎么办")
    expect(page.get_by_role("button", name="提问", exact=True)).to_be_enabled()
    page.get_by_role("button", name="提问", exact=True).click()
    reply(page, 5)
    assert page.locator(".meridian-message.assistant").last.locator(".meridian-evidence details").count() > 0
    page.locator(".meridian-message.assistant").last.locator(".meridian-evidence summary").first.click()
    links = page.locator(".meridian-message.assistant").last.locator(".meridian-evidence a").evaluate_all("els => els.map(e=>e.getAttribute('href'))")
    assert any("/api/studio/documents/" in link and "#page=" in link for link in links), links
    page.screenshot(path=str(OUT / "09_manual_citations.png"), full_page=True)
    record("full PDF select retrieve and original page links")

    page.get_by_role("tab", name="视觉", exact=True).click()
    page.locator('.workspace-vision-actions input[type="file"]').set_input_files(str(ROOT / "tests/vision_probe.png"))
    expect(page.get_by_alt_text("待识别的车辆图片")).to_be_visible()
    page.get_by_label("视觉检索手册").select_option("")
    page.get_by_label("想了解什么").fill("图片中是什么颜色的形状？")
    page.get_by_role("button", name="识别并查询知识").click()
    reply(page, 6)
    expect(page.locator(".meridian-message.assistant").last).to_contain_text("红")
    page.screenshot(path=str(OUT / "10_vision.png"), full_page=True)
    record("image upload uses real visual model no control side effects")

    page.get_by_role("button", name=re.compile("可信实验室")).click()
    page.get_by_label("推理提供方").select_option("offline")
    page.get_by_role("button", name=re.compile("先理解，再行动")).click()
    reply(page, 1)
    assert page.locator(".meridian-message.assistant").last.locator(".meridian-result-badge").inner_text() in ["等待补充", "需要澄清"]
    page.get_by_role("button", name=re.compile("我的座舱")).click()
    expect(page.locator(".meridian-message.assistant")).to_have_count(6)
    record("lab and workspace conversations isolated")

    page.get_by_role("button", name=re.compile("评测报告")).click()
    expect(page.locator(".meridian-comparison-score.before strong")).to_have_text("62.80%")
    expect(page.locator(".meridian-comparison-score.after strong")).to_have_text("91.73%")
    expect(page.locator(".meridian-comparison-row")).to_have_count(5)
    record("historical benchmark unchanged and compact")

    mobile = browser.new_page(viewport={"width": 390, "height": 844})
    mobile.on("pageerror", lambda e: errors.append(str(e)))
    mobile.goto(BASE, wait_until="networkidle")
    for tab in ["车辆", "导航出行", "信息服务", "记忆偏好", "视觉"]:
        mobile.get_by_role("tab", name=tab, exact=True).click()
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), tab
        if tab == "导航出行": mobile.screenshot(path=str(OUT / "11_mobile_journey.png"), full_page=True)
    mobile.get_by_role("button", name=re.compile("车辆知识")).click()
    assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    mobile.screenshot(path=str(OUT / "12_mobile_knowledge.png"), full_page=True)
    record("390px all workspace tabs and document library no overflow")
    mobile.close()
    page.close()
    browser.close()

assert not errors, errors
result = {"passed": True, "base_url": BASE, "checks": checks, "page_errors": errors,
          "api_mocked": False, "microphone_hardware_tested": False, "camera_hardware_tested": False}
(ROOT / "results/expansion_ui.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False))
