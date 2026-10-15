"""User-initiated real provider smoke run; writes evidence without secrets.

Run from deliverable root with .venv/bin/python tests/probe_expanded_services.py.
Temporary SQLite/notification data never reaches the user's local workspace.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cockpit-agent"))
from interview.services import Services, now


async def main():
    evidence = {"checked_at": now(), "type": "real-provider-smoke-not-benchmark", "cases": []}
    with tempfile.TemporaryDirectory() as td:
        service = Services(Path(td))
        context = {}
        tests = [
            ("search_places", {"query": "杭州东站", "limit": 5}),
            ("plan_route", {"destination": "杭州东站"}),
            ("get_weather", {"location": "杭州", "days": 3}),
            ("search_places", {"query": "附近咖啡店", "category": "cafe", "limit": 5}),
            ("plan_route", {"candidate_index": 2}),
            ("search_places", {"query": "沿途充电站", "category": "charging_station", "along_route": True, "limit": 5}),
            ("get_news", {"topic": "新能源汽车", "limit": 3}),
            ("search_web", {"query": "Volvo EC40 user manual", "limit": 3}),
        ]
        for name, args in tests:
            start = time.monotonic()
            row = await service.execute(name, args, context)
            compact = {"tool": name, "args": args, "status": row["status"], "message": row["message"],
                       "elapsed_ms": round((time.monotonic()-start)*1000), "evidence": row["evidence"],
                       "data": {k:v for k,v in row["data"].items() if k not in {"geometry"}}}
            if row["data"].get("geometry"):
                compact["geometry_points"] = len(row["data"]["geometry"]["coordinates"])
            evidence["cases"].append(compact)
            print(name, row["status"], compact["elapsed_ms"], row["message"][:100], flush=True)
        evidence["documents"] = []
        for meta in json.loads((ROOT / "data/manuals/catalog.json").read_text())["documents"]:
            content = (ROOT / "data/manuals" / meta["filename"]).read_bytes()
            assert hashlib.sha256(content).hexdigest() == meta["sha256"]
            row = service.import_pdf(content, meta["filename"], meta["vehicle"], source_url=meta["source_url"], title=meta["title"])
            evidence["documents"].append(row)
            print("import", meta["filename"], row["status"], row["message"], flush=True)
        doc = next(d for d in service.list_documents() if " UK" in d["vehicle"])
        for query in ["雨刷怎么打开", "胎压应当怎样检查", "后向儿童座椅放副驾时气囊怎么办"]:
            row = await service.execute("search_manual", {"query": query, "document_id": doc["id"]}, context)
            evidence["cases"].append({"tool": "search_manual", "query": query, **row})
            print("manual", query, row["status"], [p["page"] for p in row["data"].get("passages", [])], flush=True)
        await service.close()
    evidence["limitations"] = ["服务可用性为当前单次真实探针，不是可用性SLA。", "公共地图无实时路况/充电空闲信息，起点明确为演示坐标。", "手册原文为各自指定车型/年份/地区的英文PDF；词法召回不保证穷尽全部安全条件。", "新闻/搜索摘要和发布时刻来自外部提供商，未独立事实核查。"]
    evidence["source_sha256"] = hashlib.sha256((ROOT / "cockpit-agent/interview/services.py").read_bytes()).hexdigest()
    (ROOT / "results/expanded_services_probe.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
