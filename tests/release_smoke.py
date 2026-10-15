#!/usr/bin/env python3
"""Check a running local release without model calls or external providers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--browser", action="store_true", help="Also check Chromium UI (requires Playwright)")
    parser.add_argument("--output", type=Path, help="Optional JSON result file")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    sid = "release-" + uuid.uuid4().hex[:12]
    checks = []

    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(base + path, data=data, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as response:
            assert response.status == 200
            return json.load(response)

    def chat(text, channel="workspace"):
        return request("/api/studio/chat", {"session_id": sid, "text": text,
                       "provider": "offline", "mode": "guarded", "channel": channel})

    def reset(**overrides):
        return request("/api/studio/reset", {"session_id": sid, **overrides})

    with urlopen(base + "/", timeout=10) as response:
        assert response.status == 200 and b'<div id="root">' in response.read()
    health = request("/api/studio/health")
    assert health["ok"] and health["source"] == "simulated"
    request("/api/studio/bootstrap?session_id=" + sid)
    checks.append("frontend_and_api_available")

    reset()
    reply = chat("帮我打开一点", "lab")
    assert reply["status"] == "clarify" and not any(reply["vehicle"]["windows"].values())
    checks.append("ambiguous_request_has_no_vehicle_effect")
    reply = chat("副驾车窗开50%")
    assert reply["status"] == "executed"
    assert reply["vehicle"]["windows"]["front_right"] == 50
    assert reply["vehicle"]["windows"]["rear_right"] == 0
    checks.append("passenger_window_changes_correct_position")
    reset(profile="standard")
    assert chat("打开按摩", "lab")["status"] == "unsupported"
    checks.append("unsupported_capability_rejected")
    reset(speed=100, gear="D")
    reply = chat("打开副驾车门", "lab")
    assert reply["status"] == "blocked" and not any(reply["vehicle"]["doors"].values())
    checks.append("moving_vehicle_door_blocked")
    reset()
    reply = chat("EC40 2026后向儿童座椅放副驾，应该怎么安装？", "lab")
    assert "child.rear_front" in reply.get("fact_ids", []) and "关闭" in reply["message"]
    checks.append("curated_manual_evidence_available_without_pdf_download")

    if args.browser:
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(base, wait_until="networkidle")
            page.get_by_label("推理提供方").select_option("offline")
            page.get_by_role("textbox", name="给经纬助手发送指令").fill("副驾车窗开50%")
            page.get_by_role("button", name="发送指令", exact=True).click()
            expect(page.locator(".meridian-message.assistant").last).to_contain_text("50")
            for label in ("可信实验室", "车辆知识", "评测报告"):
                page.get_by_role("button", name=re.compile(label)).click()
            expect(page.get_by_role("heading", name="方案前后，准确率对比。")).to_be_visible()
            expect(page.get_by_label("总准确率对比")).to_contain_text("91.73%")
            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.goto(base, wait_until="networkidle")
            assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert not page_errors, page_errors
            browser.close()
        checks.append("browser_chat_four_pages_and_mobile_layout")

    result = {"passed": True, "checks": checks, "model_calls": 0,
              "external_provider_queries": 0, "vehicle_source": "simulated"}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
