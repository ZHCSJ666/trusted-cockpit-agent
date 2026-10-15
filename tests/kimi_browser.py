"""One real Kimi request through the browser, separate from offline UI smoke."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto("http://127.0.0.1:8787", wait_until="networkidle")
    page.get_by_label("推理提供方").select_option("kimi")
    page.get_by_role("textbox", name="给经纬助手发送指令").fill("副驾车窗开50%")
    with page.expect_response(lambda r: r.url.endswith("/api/studio/chat"), timeout=100000) as pending:
        page.get_by_role("button", name="发送指令", exact=True).click()
    result = pending.value.json()
    assert result["provider"] == "kimi" and result["model"]["model"]
    assert result["status"] == "executed" and result["vehicle"]["windows"]["front_right"] == 50
    assert result["vehicle"]["windows"]["rear_right"] == 0
    expect(page.get_by_role("textbox", name="给经纬助手发送指令")).to_be_enabled()
    page.screenshot(path=str(ROOT/"results/screenshots/09_kimi_live.png"), full_page=True)
    (ROOT/"results/kimi_browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"status": result["status"], "model": result["model"], "window": result["vehicle"]["windows"]}, ensure_ascii=False))
    browser.close()
