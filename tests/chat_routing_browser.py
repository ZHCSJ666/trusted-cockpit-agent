"""Type the reported phrases into the real HMI; no model/service mocks."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("STUDIO_TEST_URL", "http://127.0.0.1:8788")
OUT = ROOT / "results/chat_routing"
OUT.mkdir(exist_ok=True)
records, checks, errors = [], [], []


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    page.set_default_timeout(20000)
    sid = "chat-route-" + uuid.uuid4().hex[:10]
    page.add_init_script(f"sessionStorage.setItem('meridian.session', {json.dumps(sid)})")
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    expect(page.get_by_label("推理提供方")).to_have_value("kimi")

    def chat(text):
        page.get_by_label("给经纬助手发送指令").fill(text)
        with page.expect_response(lambda r: r.url.endswith("/api/studio/chat/stream"), timeout=180000) as response:
            page.get_by_label("发送指令", exact=True).click()
        body = response.value.text()
        finals = [event for event in body.split("\n\n") if event.startswith("event: final\n")]
        assert len(finals) == 1, body[:300]
        data = json.loads(finals[0].split("data: ", 1)[1])
        expect(page.get_by_label("给经纬助手发送指令")).to_be_enabled(timeout=180000)
        assert "没有提供可验证的工具计划" not in data["message"]
        record = {"input": text, **{k: data.get(k) for k in ["status", "message", "calls", "model", "orchestration", "trace"]}}
        record["steps"] = [{k: s.get(k) for k in ["tool", "args", "status"]} for s in data["steps"]]
        records.append(record)
        print(json.dumps({"input": text, "status": data["status"], "steps": record["steps"]}, ensure_ascii=False), flush=True)
        return data

    r = chat("从杭州西湖出发，到杭州东站，帮我规划驾车路线")
    assert r["steps"][0]["tool"] == "plan_route"
    assert r["steps"][0]["args"] == {"origin": "杭州西湖", "destination": "杭州东站"}
    if r["status"] == "clarify":
        assert "起点" in r["message"], r["message"]
        choices = r["workspace"]["places"]
        chosen = next(i for i, place in enumerate(choices, 1) if place["name"] == "杭州西湖风景名胜区")
        r = chat(f"第{chosen}个")
    assert r["status"] == "executed", r["message"]
    route = r["workspace"]["last_route"]
    assert "西湖" in route["origin"]["name"]
    assert route["destination"]["name"] in {"杭州东", "杭州东站", "杭州东站火车站"} and route["destination"]["kind"] == "station"
    assert route["distance_m"] > 0 and len(route["geometry"]["coordinates"]) > 2
    page.get_by_role("tab", name="导航出行").click()
    expect(page.locator(".workspace-route-summary")).to_be_visible()
    assert page.locator('.workspace-map path[stroke="#456fa4"]').count() > 0
    page.screenshot(path=str(OUT / "route.png"), full_page=True)
    checks.append("Typed explicit endpoints, legitimate origin disambiguation, continued original route and real map geometry")

    r = chat("给我查一下今天有什么新闻")
    assert r["steps"][0]["tool"] == "get_news" and r["steps"][0]["args"] == {"period": "today"}
    feed = r["workspace"]["last_news"]
    assert feed["period"] == "today" and feed["topic"] == "综合新闻"
    if feed["items"]:
        assert r["status"] == "answered"
        for item in feed["items"]:
            assert parsedate_to_datetime(item["published_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() == feed["requested_date"]
            assert item["url"] and item["source"]
    else:
        assert r["status"] == "unavailable" and "未用旧新闻代替" in r["message"]
    records[-1]["news"] = feed
    page.get_by_role("tab", name="信息服务").click()
    page.screenshot(path=str(OUT / "news.png"), full_page=True)
    checks.append("Typed today's general news, verified published dates or honest no-current-items result")

    r = chat("劳驾找点汽车行业资讯给我看看")
    assert any(s["tool"] == "get_news" for s in r["steps"]), r["message"]
    assert r["status"] == "answered" and r["workspace"]["last_news"]["items"], r["message"]
    assert r.get("model"), "Natural unmatched phrasing must exercise the real model planner"
    checks.append("Unmatched natural wording reaches actual model and news provider after prior route/news conversation")
    assert not errors, errors
    browser.close()

report = {"passed": True, "at": datetime.now(timezone.utc).isoformat(), "checks": checks,
          "count": len(checks), "model_replies_mocked": False, "provider_results_mocked": False,
          "browser_input": "typed original phrases, not feature buttons", "records": records}
(ROOT / "results/chat_routing_acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"passed": True, "checks": len(checks)}, ensure_ascii=False))
