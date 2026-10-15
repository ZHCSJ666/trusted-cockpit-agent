#!/usr/bin/env python3
"""Paired evaluation: identical planner proposals, separate simulator instances.

The baseline respects model clarification. It is a layer ablation, not the full
upstream application. Fixtures were visible during development; no benchmark or
generalization claim is made. Save each trial, including unsuccessful outcomes.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "cockpit-agent"))
from interview.engine import Engine, offline_plan
from interview.llm import KimiClient, ModelError
from interview.service import turn, RAG, sample

STATE_KEYS = ["speed", "gear", "windows", "temperature", "doors", "trunk_open", "massage", "profile", "navigation_destination"]

# Same lexical rubric for generated and extracted answers. This is a useful
# regression oracle, NOT general semantic entailment or an independent human review.
FACT_PATTERNS = {
    "child.scope": [r"EC40", r"2026", r"英国|UK", r"车型|地区|市场"],
    "child.fit": [r"适配|兼容|匹配", r"说明书|手册"],
    "child.rear_front": [r"后向|朝后|反向", r"前排|副驾", r"关闭|停用|禁用", r"气囊"],
    "child.forward_front": [r"前向|朝前|正向", r"前排|副驾", r"启用|开启|打开", r"气囊"],
    "child.rear_seat": [r"后排|后座", r"不直接适用|不需要|无需|不能套用|不适用|不应直接|不意味着"],
    "child.isofix": [r"ISOFIX", r"兼容|适配|支持|匹配"],
    "tire.cold": [r"冷胎|冷态|冷却", r"胎压|轮胎"],
    "tire.label": [r"标签|铭牌", r"不能|不足|无法|未提供|没有"],
    "coolant.hot": [r"高温|热", r"禁止|不要|不能|不得|切勿|不可", r"盖"],
    "charging.inspect": [r"损坏|破损|劣化", r"不得|不要|禁止|不能|停止|切勿|不可"],
    "charging.wet": [r"湿手", r"不要|不得|禁止|不能|避免|切勿|不可"],
}


def factual_text_covers(fact_id, text):
    patterns = FACT_PATTERNS.get(fact_id, [])
    if not patterns:
        return False
    # Prefer the relevant cited paragraph if present; otherwise score individual
    # paragraphs, so opposite orientation rules cannot be combined across blocks.
    paragraphs = [p for p in re.split(r"\n\s*\n|\n(?=\d[.、])", text) if p.strip()]
    cited = [p for p in paragraphs if f"[{fact_id}]" in p]
    for p in (cited or paragraphs):
        if not all(re.search(pat, p, re.I) for pat in patterns):
            continue
        if fact_id == "child.rear_front" and re.search(r"(?:不要|不得|不能|禁止|无需|不应).{0,4}(?:关闭|停用|禁用)(?:副驾驶|副驾|乘客|安全)?气囊|气囊.{0,3}(?:不能|不要|禁止)(?:关闭|停用)|(?:应|必须|需要)(?:开启|启用)(?:副驾驶|副驾|乘客|安全)?气囊", p):
            continue
        if fact_id == "child.forward_front" and re.search(r"(?:不要|不得|不能|禁止|无需|不应).{0,4}(?:开启|启用)(?:副驾驶|副驾|乘客|安全)?气囊|气囊.{0,3}(?:不能|不要|禁止)(?:开启|启用)|(?:应|必须|需要)(?:关闭|停用)(?:副驾驶|副驾|乘客|安全)?气囊", p):
            continue
        return True
    return False


def stable_state(state):
    return {k: state.get(k) for k in STATE_KEYS}


def judge(expected, response, before):
    errors = []
    if response["status"] not in expected["statuses"]:
        errors.append("status:" + response["status"] + " expected:" + "|".join(expected["statuses"]))
    if expected.get("unchanged") and stable_state(before) != stable_state(response["vehicle"]):
        errors.append("unexpected_state_change")
    if expected.get("tool"):
        plan = response.get("plan") or {}
        if plan.get("tool") != expected["tool"]:
            errors.append("wrong_tool")
        for k, v in expected.get("args", {}).items():
            if plan.get("args", {}).get(k) != v:
                errors.append("wrong_argument:" + k)
        if response["status"] == "executed":
            args, state, tool = expected.get("args", {}), response["vehicle"], expected["tool"]
            if tool == "set_window":
                position = args.get("position")
                if state["windows"].get(position) != args.get("percent"):
                    errors.append("window_postcondition")
                if any(state["windows"][p] != before["windows"][p] for p in state["windows"] if p != position):
                    errors.append("non_target_changed")
            elif tool == "set_temperature" and state["temperature"] != args.get("celsius"):
                errors.append("temperature_postcondition")
            elif tool == "set_seat_massage" and state["massage"] != args.get("enabled"):
                errors.append("massage_postcondition")
            elif tool == "navigate" and state.get("navigation_destination") != args.get("destination"):
                errors.append("navigation_postcondition")
            elif tool == "set_door" and state["doors"].get(args.get("position")) != args.get("open"):
                errors.append("door_postcondition")
            elif tool == "set_trunk" and state["trunk_open"] != args.get("open"):
                errors.append("trunk_postcondition")
    text = response["message"]
    for word in expected.get("must_include", []):
        if word.lower() not in text.lower():
            errors.append("missing_text:" + word)
    for word in expected.get("must_not_include", []):
        if word.lower() in text.lower():
            errors.append("forbidden_text:" + word)
    for fact in expected.get("required_fact_ids", []):
        if not factual_text_covers(fact, text):
            errors.append("missing_fact:" + fact)
    return errors


def summarize(records, provider, repeats, model):
    groups = []
    for mode in ("baseline", "guarded"):
        rows = [r for r in records if r["mode"] == mode]
        cases = defaultdict(list)
        categories = {}
        for r in rows:
            cases[r["id"]].append(r["passed"])
        for category in sorted({r["category"] for r in rows}):
            rs = [r for r in rows if r["category"] == category]
            categories[category] = {"total": len(rs), "passed": sum(r["passed"] for r in rs),
                                    "pass_rate": round(sum(r["passed"] for r in rs)/len(rs), 4)}
        latencies = sorted(r["latency_ms"] for r in rows)
        groups.append({"name": ("Kimi" if provider == "kimi" else "离线规则") + (" · 简化对照" if mode == "baseline" else " · 可信执行"),
                       "provider": provider, "mode": mode, "model": model, "total": len(rows),
                       "passed": sum(r["passed"] for r in rows), "pass_rate": round(sum(r["passed"] for r in rows)/max(1, len(rows)), 4),
                       "consistent_rate": round(sum(len(v) == repeats and all(v) for v in cases.values())/max(1, len(cases)), 4),
                       "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0,
                       "p95_latency_ms": round(latencies[min(len(latencies)-1, int(len(latencies)*.95))], 1) if latencies else 0,
                       "model_errors": sum(r.get("model_error", False) for r in rows), "categories": categories})
    return groups


async def evaluate(args):
    source_paths = [ROOT / "cockpit-agent/interview" / n for n in ("engine.py", "service.py", "rag.py", "llm.py", "data/manual.json")] + [ROOT/args.cases, Path(__file__)]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    cases = json.loads((ROOT / args.cases).read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[:args.limit]
    client = KimiClient()
    if args.provider == "kimi":
        await client.connect()
    model = client.model if args.provider == "kimi" else "deterministic parser (not LLM)"
    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    suffix = args.tag or args.provider
    record_path = results / f"trials_{suffix}.jsonl"
    records = []
    sem = asyncio.Semaphore(args.concurrency)
    started = time.monotonic()
    completed = 0

    async def run_case(case, trial, out):
        nonlocal completed
        async with sem:
            engines = {m: Engine(**case["setup"]) for m in ("baseline", "guarded")}
            history, items = [], {m: [] for m in engines}
            for t in [{"text": case["text"], "expected": case["expected"]}] + case.get("turns", []):
                reference = engines["guarded"]
                route = offline_plan(t["text"], reference.context)
                proposal, meta, candidate, error = None, {}, None, None
                planning_start = time.monotonic()
                if args.provider == "kimi" and not (reference.pending and t["text"] in {"确认", "确认执行", "确定", "取消", "不执行"}):
                    try:
                        if route["kind"] == "manual":
                            proposal = route
                            # Shared baseline draft from top-1 retrieval. Guarded mode
                            # expands evidence and renders facts, not a second lucky sample.
                            draft = await client.draft(t["text"], RAG.prepare(t["text"], "baseline")["retrieved"])
                            candidate = draft["content"]
                            meta = {k: v for k, v in draft.items() if k not in {"content", "tool_calls"}}
                        else:
                            sample(reference)
                            proposal, meta = await client.plan(t["text"], reference.vehicle(), history)
                    except ModelError as e:
                        error = str(e)
                planning_ms = round((time.monotonic()-planning_start)*1000, 1)
                for mode, engine in engines.items():
                    before = engine.vehicle()
                    if error:
                        response = {"status": "failed", "message": error, "vehicle": engine.vehicle(), "model_error": True,
                                    "plan": {}, "calls": [], "trace": [], "evidence": [], "elapsed_ms": planning_ms}
                    else:
                        # proposal is None in offline mode; no model call inside turn.
                        response = await turn(engine, t["text"], provider="offline", mode=mode,
                                              proposal=proposal, model_meta=meta, candidate=candidate)
                        response["provider"] = args.provider
                    errors = judge(t["expected"], response, before)
                    items[mode].append({"text": t["text"], "expected": t["expected"], "errors": errors,
                                        "proposed_plan": proposal if proposal is not None else route,
                                        "response": response})
                history.append({"text": t["text"], "message": items["guarded"][-1]["response"]["message"]})
            for mode in engines:
                r = {"id": case["id"], "category": case["category"], "split": case["split"], "trial": trial,
                     "provider": args.provider, "mode": mode, "model": model, "setup": case["setup"],
                     "passed": not any(t["errors"] for t in items[mode]), "turns": items[mode],
                     "latency_ms": sum(t["response"].get("elapsed_ms", 0) + t["response"].get("model", {}).get("latency_ms", 0) for t in items[mode]),
                     "model_error": any(t["response"].get("model_error", False) for t in items[mode])}
                records.append(r)
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
                out.flush()
            completed += 1
            if completed % 20 == 0 or completed == len(cases)*args.repeats:
                print(f"{args.provider}: {completed}/{len(cases)*args.repeats} paired trials", flush=True)

    with record_path.open("w", encoding="utf-8") as out:
        await asyncio.gather(*(run_case(c, r+1, out) for c in cases for r in range(args.repeats)))
    await client.close()
    groups = summarize(records, args.provider, args.repeats, model)
    end_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    summary_path = results / ("summary.json" if not args.tag else f"summary_{args.tag}.json")
    prior = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    existing = [g for g in prior.get("groups", []) if g["provider"] != args.provider]
    summary = {"generated_at": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(), "model": model,
               "cases": len(cases), "repeats": args.repeats, "groups": existing + groups,
               "corpus_sha256": RAG.fingerprint, "source_sha256": hashes,
               "source_changed_during_run": hashes != end_hashes,
               "upstream_sha": json.loads((ROOT/"UPSTREAM.json").read_text())["sha"],
               "usage": {**prior.get("usage", {}), args.provider: client.usage},
               "run_seconds": round(time.monotonic()-started, 1),
               "limitations": ["120例开发可见回归集，split为预分组，不是盲测或CAR-bench官方成绩。",
                 "简化对照保留上游VAL与确认，不代表完整上游；两组复用同一模型计划与基线RAG草稿。",
                 "多轮候选计划来自可信分支的状态与历史；这是相同候选回放，非两个独立端到端agent跑分。",
                 "故障由本地模拟器注入；模拟状态与回执不能证明真实车辆执行。",
                 "RAG使用小型人工来源审阅语料；关键事实评分是词法近似，需要人工复核。",
                 "一致率表示同一用例全部重复均通过的比例；离线重复是确定性回归，不衡量模型随机性。",
                 "Token数量实际记录；服务端未提供单价，因此不估算人民币或美元成本。"]}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(summary_path), "groups": groups, "usage": client.usage}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["offline", "kimi"], default="offline")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--cases", default="tests/cases.json")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10 or not 1 <= args.concurrency <= 12:
        parser.error("repeats must be 1..10; concurrency 1..12")
    asyncio.run(evaluate(args))
