"""Actual typed navigation questions and manual-to-navigation task switching."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("STUDIO_TEST_URL", "http://127.0.0.1:8788")
OUT = ROOT / "results/navigation_question"
OUT.mkdir(exist_ok=True)
QUESTION = "帮我查询一下怎么去杭州市政府"
records, checks, errors = [], [], []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    page.set_default_timeout(20000)
    sid = "nav-question-" + uuid.uuid4().hex[:10]
    page.add_init_script(f"sessionStorage.setItem('meridian.session', {json.dumps(sid)})")
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")

    def chat(text):
        page.get_by_label("给经纬助手发送指令").fill(text)
        with page.expect_response(lambda r: r.url.endswith("/api/studio/chat/stream"), timeout=180000) as response:
            page.get_by_label("发送指令", exact=True).click()
        finals = [event for event in response.value.text().split("\n\n") if event.startswith("event: final\n")]
        assert len(finals) == 1
        data = json.loads(finals[0].split("data: ", 1)[1])
        expect(page.get_by_label("给经纬助手发送指令")).to_be_enabled(timeout=180000)
        record = {"input": text, **{k: data.get(k) for k in ["status", "message", "calls", "model", "orchestration", "trace"]}}
        record["steps"] = [{k: s.get(k) for k in ["tool", "args", "status"]} for s in data["steps"]]
        route = data.get("workspace", {}).get("last_route")
        if route:
            record["route"] = {k: v for k, v in route.items() if k != "geometry"}
            record["route"]["geometry_points"] = len(route["geometry"]["coordinates"])
        records.append(record)
        (ROOT / "results/navigation_question_trials.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"input": text, "status": data["status"], "steps": record["steps"]}, ensure_ascii=False), flush=True)
        return data

    def valid_route(r):
        assert r["status"] == "executed", r["message"]
        assert [s["tool"] for s in r["steps"]] == ["plan_route"]
        assert r["steps"][0]["args"] == {"destination": "杭州市政府"}
        route = r["workspace"]["last_route"]
        assert route["destination"]["name"] == "杭州市人民政府"
        assert route["destination"]["query_alias"] == "杭州市人民政府"
        assert route["destination"]["source_url"].startswith("https://www.openstreetmap.org/")
        assert route["distance_m"] > 0 and len(route["geometry"]["coordinates"]) > 2

    valid_route(chat(QUESTION))
    checks.append("Original typed question executes plan_route with verified government POI and real route")
    page.get_by_role("tab", name="导航出行").click()
    expect(page.locator(".workspace-route-summary")).to_contain_text("杭州市人民政府")
    assert page.locator('.workspace-map path[stroke="#456fa4"]').count() > 0
    page.screenshot(path=str(OUT / "government_route.png"), full_page=True)

    r = chat("如何安装儿童座椅")
    assert r["status"] == "clarify" and r["steps"][0]["tool"] == "search_manual"
    valid_route(chat(QUESTION))
    checks.append("Pending manual choice does not trap the next navigation request in the same conversation")

    valid_route(chat("杭州市政府怎么走？"))
    checks.append("Place-first travel question preserves the requested destination")

    r = chat("怎么去除车窗雾气")
    assert r["status"] == "clarify" and [s["tool"] for s in r["steps"]] == ["search_manual"]
    assert not any(c.get("tool") in {"set_window", "plan_route"} for c in r["calls"])
    checks.append("Vehicle how-to remains a manual question with no vehicle operation")

    r = chat(QUESTION + "，然后查杭州天气")
    names = {s["tool"] for s in r["steps"] if s["status"] in {"executed", "answered"}}
    assert {"plan_route", "get_weather"} <= names, r["message"]
    assert r.get("model") and r["workspace"]["last_route"]["destination"]["name"] == "杭州市人民政府"
    checks.append("Compound query leaves pending manual, uses real Kimi and executes both route and weather")
    assert not errors, errors
    browser.close()

report = {"passed": True, "at": datetime.now(timezone.utc).isoformat(), "checks": checks,
          "count": len(checks), "model_replies_mocked": False, "provider_results_mocked": False,
          "browser_input": "typed into assistant", "records": records}
(ROOT / "results/navigation_question_acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"passed": True, "checks": len(checks)}, ensure_ascii=False))
