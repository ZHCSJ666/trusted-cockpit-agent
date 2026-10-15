"""Exercise the expanded local API with real providers; never mock model replies.

Run against a dedicated preview process: .venv/bin/python tests/expansion_api.py --port 8788
Only temporary QA preferences/reminders are written and subsequently removed.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]


async def main(port):
    checks, trials = [], []
    sid = "acceptance_" + uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=180, trust_env=False) as client:
        async def post(path, payload):
            response = await client.post("/api/studio/" + path, json={"session_id": sid, **payload})
            response.raise_for_status()
            return response.json()

        async def chat(text, provider="kimi", **extra):
            response = await post("chat", {"text": text, "provider": provider, **extra})
            trials.append({"input": text, "response": response})
            (ROOT / "results/expansion_acceptance_trials.json").write_text(json.dumps(trials, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"input": text, "status": response["status"], "steps": [s["tool"] for s in response.get("steps", [])]}, ensure_ascii=False), flush=True)
            return response

        health = (await client.get("/api/studio/health")).json()
        assert health["version"] == "2.0.0"
        boot = (await client.get("/api/studio/bootstrap", params={"session_id": sid})).json()
        assert len(boot["workspace"]["documents"]) >= 3
        checks.append("expanded startup and full manuals")

        response = await chat("天窗开30%，然后打开氛围灯", "offline")
        assert response["vehicle"]["sunroof_percent"] == 30 and response["vehicle"]["lights"]["ambient"]
        assert len(response["steps"]) == 2
        response = await chat("副驾座椅加热设为2挡", "offline")
        assert response["vehicle"]["seats"]["front_right"]["heating"] == 2
        assert response["vehicle"]["seats"]["front_left"]["heating"] == 0
        checks.append("new VAL controls and non-target state")

        await post("reset", {"speed": 100, "gear": "D"})
        response = await chat("主驾座椅靠背调到120度", "offline")
        assert response["status"] == "blocked" and response["vehicle"]["seats"]["front_left"]["recline"] == 90
        await post("reset", {})
        response = await chat("帮我打开一点")
        assert response["status"] == "clarify" and not response["calls"]
        checks.append("new safety and existing ambiguity")

        response = await chat("查杭州天气，导航去杭州东站，并把空调设为22度")
        names = {s["tool"] for s in response["steps"] if s["status"] in {"answered", "executed"}}
        assert {"get_weather", "plan_route", "set_temperature"} <= names
        route = response["workspace"]["last_route"]
        assert route["distance_m"] > 0 and len(route["geometry"]["coordinates"]) > 2
        destination = route["destination"]["name"]
        checks.append("real model cross-domain plan, weather and route")

        response = await chat("搜索附近的咖啡店")
        assert len(response["workspace"]["places"]) >= 2
        second = response["workspace"]["places"][1]["name"]
        response = await chat("把第二家加入途经点")
        route = response["workspace"]["last_route"]
        assert response["status"] == "executed" and route["destination"]["name"] == destination
        assert second in [p["name"] for p in route["waypoints"]]
        checks.append("real POI selection, cross-turn waypoint preserves destination")

        response = await chat("最新汽车新闻")
        assert response["workspace"]["last_news"]["items"]
        response = await chat("搜索 OpenStreetMap 是什么")
        assert response["workspace"]["last_search"]["items"]
        checks.append("real RSS news and web search with sources")

        key = "acceptance_" + uuid.uuid4().hex[:8]
        await post("preferences", {"key": key, "value": "无糖拿铁"})
        fresh = (await client.get("/api/studio/workspace", params={"session_id": sid + "_new"})).json()
        assert any(p["key"] == key and p["value"] == "无糖拿铁" for p in fresh["preferences"])
        await post("preferences", {"key": key, "value": "茶"})
        await client.delete(f"/api/studio/preferences/{key}", params={"session_id": sid})
        fresh = (await client.get("/api/studio/workspace", params={"session_id": sid + "_new"})).json()
        assert not any(p["key"] == key for p in fresh["preferences"])
        checks.append("persistent preference cross-session update and deletion")

        response = await chat("3秒后提醒我进行验收休息", "offline")
        created = [r for r in response["workspace"]["reminders"] if r["message"] == "进行验收休息"]
        assert len(created) == 1
        await asyncio.sleep(3.3)
        due = (await client.get("/api/studio/reminders/due", params={"session_id": sid})).json()
        assert created[0]["id"] in [r["id"] for r in due["due"]]
        due2 = (await client.get("/api/studio/reminders/due", params={"session_id": sid})).json()
        assert created[0]["id"] not in [r["id"] for r in due2["due"]]
        await client.delete("/api/studio/reminders/" + created[0]["id"], params={"session_id": sid})
        checks.append("persistent reminder due notification is single-consumption")

        doc = next(d for d in boot["workspace"]["documents"] if d["vehicle"] == "Volvo EC40 2026 UK")
        await post("workspace", {"document_id": doc["id"]})
        response = await chat("查询手册：胎压警告是什么意思？", "offline")
        assert response["status"] == "answered" and response["evidence"]
        assert response["workspace"]["last_manual"]["document"]["id"] == doc["id"]
        file = await client.get(f"/api/studio/documents/{doc['id']}/file")
        assert file.status_code == 200 and file.content.startswith(b"%PDF")
        invalid = await client.post("/api/studio/documents/import", data={"vehicle": "QA"}, files={"file": ("bad.pdf", b"not a PDF", "application/pdf")})
        assert invalid.status_code == 422
        missing = await client.get("/api/studio/documents/nonexistent/file")
        assert missing.status_code == 404
        checks.append("full manual retrieval, vehicle scope, PDF pages and invalid import")

        image = "data:image/png;base64," + base64.b64encode((ROOT / "tests/vision_probe.png").read_bytes()).decode()
        response = await post("vision", {"image": image, "question": "描述图中的颜色和形状。"})
        trials.append({"input": "synthetic red square and blue circle image", "response": response})
        assert "红" in response["message"] and "蓝" in response["message"] and not response["calls"]
        checks.append("real multimodal model, image read-only")

        events = []
        async with client.stream("POST", "/api/studio/chat/stream", json={"session_id": sid, "text": "雨刷调到2挡", "provider": "offline"}) as stream:
            async for line in stream.aiter_lines():
                if line.startswith("event: "):
                    events.append(line[7:])
        assert "progress" in events and events[-1] == "final"
        checks.append("actual SSE progress and final result")

    report = {"passed": True, "at": datetime.now(timezone.utc).isoformat(), "checks": checks,
              "count": len(checks), "model_replies_mocked": False, "provider_results_mocked": False,
              "not_tested": ["physical microphone/camera/speakers", "real vehicle", "live traffic", "charging availability"],
              "trials": trials}
    (ROOT / "results/expansion_acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": len(checks)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8788)
    asyncio.run(main(parser.parse_args().port))
