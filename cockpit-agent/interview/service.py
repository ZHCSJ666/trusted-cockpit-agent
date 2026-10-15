"""Shared turn orchestration for HTTP and reproducible evaluations."""
from __future__ import annotations

import time
from .engine import Engine, offline_plan
from .llm import KimiClient, ModelError
from .rag import ManualRAG

RAG = ManualRAG()


def sample(engine):
    if hasattr(engine, "sample_state"):
        engine.sample_state()


async def turn(engine: Engine, text: str, *, provider="offline", mode="guarded", client: KimiClient | None = None,
               history=None, proposal=None, model_meta=None, candidate=None):
    start = time.monotonic()
    sample(engine)
    before = engine.vehicle()
    if engine.pending and text.strip() in {"确认", "确认执行", "确定", "取消", "不执行"}:
        result = engine.confirm(engine.pending["token"], approve=text.strip() not in {"取消", "不执行"})
    else:
        # A new utterance revokes the old confirmation even when model I/O fails.
        # Confirmation can only authorize the most recent still-pending request.
        if engine.pending:
            engine.pending = None
        route = offline_plan(text, engine.context)
        meta = model_meta or {}
        try:
            if provider == "kimi" and proposal is None:
                if not client:
                    raise ModelError("Kimi服务未初始化。")
                if route.get("kind") == "manual":
                    proposal = route
                    material = RAG.prepare(text, mode)["retrieved"]
                    draft = await client.draft(text, material)
                    candidate, meta = draft["content"], {k: v for k, v in draft.items() if k not in {"content", "tool_calls"}}
                else:
                    proposal, meta = await client.plan(text, engine.vehicle(), history)
            sample(engine)  # A fresh sample from our local simulator; stale-fault samples remain stale.
            result = engine.process(text, proposal, mode)
            if result.get("plan", {}).get("kind") == "manual":
                # Original question is authoritative; a planner rewrite cannot drop qualifiers.
                answer = RAG.answer(text, mode=mode, candidate=candidate)
                result.update(status=answer["status"], message=answer["message"], evidence=answer["evidence"],
                              fact_ids=answer["fact_ids"], candidate=candidate)
                result["trace"] += answer["trace"]
            if meta:
                result["model"] = meta
                result["trace"].insert(1, {"stage": "model", "status": "ok", "detail": meta})
        except ModelError as e:
            engine.context = {}
            result = {"status": "failed", "message": str(e), "vehicle": engine.vehicle(), "calls": [], "evidence": [],
                      "trace": [{"stage": "model", "status": "failed", "detail": str(e)}], "plan": {}, "source": "simulated", "model_error": True}
    result.update(before=before, vehicle=engine.vehicle(), provider=provider, mode=mode,
                  elapsed_ms=round((time.monotonic()-start)*1000, 1))
    return result
