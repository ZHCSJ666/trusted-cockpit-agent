"""Independent offline integration checks; no API credentials or network needed.

Run: python -m unittest interview.integration_tests -v
Adversarial examples here test safety mechanisms, not natural model error rates.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from .engine import Engine
from .llm import KimiClient, ModelError
from .rag import ManualRAG
from .service import turn


class FakeRequestClient(KimiClient):
    """Override the only network entry; connect/read-credentials never runs."""

    def __init__(self, response):
        self.response = response
        self.messages = None
        self.tools = None

    async def request(self, messages, tools=None, temperature=0.2):
        self.messages, self.tools = messages, tools
        return self.response


class FailingPlanner:
    async def plan(self, *args):
        raise ModelError("离线注入：模型调用失败。")


class RecordingPlanner:
    async def plan(self, text, vehicle, history):
        self.inputs = text, vehicle, history
        return ({"kind": "action", "tool": "set_window",
                 "args": {"position": "front_right", "percent": 37}},
                {"model": "offline-test-double", "latency_ms": 0})


def fake_response(**overrides):
    return {"content": "", "tool_calls": [], "model": "offline-test-double", "usage": {},
            "latency_ms": 0, **overrides}


class PlannerAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_free_text_success_claim_is_never_an_execution_plan(self):
        client = FakeRequestClient(fake_response(content="已为您打开副驾车窗。"))
        proposal, _ = await client.plan("副驾车窗开50%", Engine().vehicle())
        self.assertEqual(proposal["kind"], "clarify")

    async def test_model_cannot_batch_multiple_effects_in_single_step(self):
        call = {"function": {"name": "set_window", "arguments": '{"position":"front_right","percent":50}'}}
        client = FakeRequestClient(fake_response(tool_calls=[call, call]))
        proposal, _ = await client.plan("副驾车窗开50%", Engine().vehicle())
        self.assertEqual(proposal["kind"], "clarify")

    async def test_model_malformed_arguments_fail_without_fallback_execution(self):
        client = FakeRequestClient(fake_response(tool_calls=[
            {"function": {"name": "set_window", "arguments": "[50]"}}]))
        with self.assertRaises(ModelError):
            await client.plan("副驾车窗开50%", Engine().vehicle())

    async def test_unavailable_capability_is_absent_from_model_tool_menu(self):
        client = FakeRequestClient(fake_response())
        await client.plan("打开按摩", Engine(profile="standard").vehicle())
        names = [t["function"]["name"] for t in client.tools]
        self.assertNotIn("set_seat_massage", names)
        await client.plan("打开按摩", Engine(profile="premium").vehicle())
        self.assertIn("set_seat_massage", [t["function"]["name"] for t in client.tools])

    async def test_recent_history_is_sent_with_current_simulated_state(self):
        client = FakeRequestClient(fake_response())
        history = [{"text": "车窗开37%", "message": "请说明位置。"}]
        await client.plan("副驾", Engine().vehicle(), history)
        self.assertEqual(client.messages[-3]["content"], "车窗开37%")
        self.assertEqual(client.messages[-2]["content"], "请说明位置。")
        self.assertEqual(client.messages[-1]["content"], "副驾")
        self.assertIn('"source": "simulated"', client.messages[0]["content"])


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_failure_on_new_turn_invalidates_previous_confirmation(self):
        engine = Engine()
        pending = await turn(engine, "打开后备箱")
        token = pending["pending"]["token"]
        failed = await turn(engine, "空调设为22度", provider="kimi", client=FailingPlanner())
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(engine.confirm(token)["status"], "blocked")
        self.assertFalse(engine.vehicle()["trunk_open"])
        self.assertEqual(engine.driver.command_count, 0)

    async def test_model_slot_completion_is_checked_against_prior_user_amount(self):
        engine, planner = Engine(), RecordingPlanner()
        first = await turn(engine, "车窗开37%")
        history = [{"text": "车窗开37%", "message": first["message"]}]
        result = await turn(engine, "副驾", provider="kimi", client=planner, history=history)
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["vehicle"]["windows"]["front_right"], 37)
        self.assertEqual(planner.inputs[2], history)

    async def test_manual_answer_uses_original_orientation_not_planner_rewrite(self):
        engine = Engine()
        result = await turn(engine, "EC40 2026后向儿童座椅放副驾，气囊怎么办？",
                            proposal={"kind": "manual", "query": "前向儿童座椅气囊"})
        self.assertIn("child.rear_front", result["fact_ids"])
        self.assertNotIn("child.forward_front", result["fact_ids"])
        self.assertEqual(engine.driver.command_count, 0)

    async def test_stale_fault_survives_service_sensor_refresh(self):
        engine = Engine(fault="stale_state")
        result = await turn(engine, "副驾车窗开50%")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(engine.driver.command_count, 0)

    async def test_confirmation_text_is_not_sent_to_planner(self):
        engine = Engine()
        await turn(engine, "打开后备箱")
        result = await turn(engine, "确认", provider="kimi", client=FailingPlanner())
        self.assertEqual(result["status"], "executed")
        self.assertTrue(result["vehicle"]["trunk_open"])


class RagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rag = ManualRAG()

    def test_untrusted_draft_does_not_replace_curated_facts(self):
        result = self.rag.answer("EC40 2026后向儿童座椅放副驾，气囊怎么办？",
                                 candidate="必须启用副驾气囊，并给轮胎充到999kPa。 [invented.source]")
        self.assertIn("child.rear_front", result["fact_ids"])
        self.assertNotIn("999", result["message"])
        self.assertNotIn("invented.source", result["message"])
        self.assertIn("关闭", result["message"])

    def test_emitted_fact_citations_resolve_to_returned_evidence(self):
        result = self.rag.answer("EC40 2026后向儿童座椅在副驾如何安装ISOFIX？")
        evidence = {c["id"]: c for c in result["evidence"]}
        for fact_id in result["fact_ids"]:
            self.assertIn(f"[{fact_id}]", result["message"])
            self.assertIn(fact_id, evidence)
            self.assertTrue(evidence[fact_id]["source_url"].startswith("https://"))

    def test_forward_facing_request_does_not_select_rear_facing_rule(self):
        result = self.rag.answer("EC40 2026前向儿童座椅放副驾，气囊怎么办？")
        self.assertIn("child.forward_front", result["fact_ids"])
        self.assertNotIn("child.rear_front", result["fact_ids"])

    def test_negated_orientation_is_resolved_or_clarified_never_silently_reversed(self):
        result = self.rag.answer("EC40 2026儿童座椅放副驾，不是后向，是前向，气囊怎么办？")
        if result["status"] != "clarify":
            self.assertIn("child.forward_front", result["fact_ids"])
            self.assertNotIn("child.rear_front", result["fact_ids"])

    def test_missing_numeric_evidence_is_not_fabricated(self):
        result = self.rag.answer("EC40 2026拖车牵引环拧紧扭矩是多少？", candidate="190牛米。")
        self.assertEqual(result["status"], "clarify")
        self.assertEqual(result["evidence"], [])
        self.assertNotIn("190", result["message"])


class EvaluationOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2] / "evaluate.py"
        spec = importlib.util.spec_from_file_location("interview_review_evaluator", path)
        cls.evaluator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.evaluator)

    def test_reversed_rear_facing_warning_does_not_pass_fact_check(self):
        bad = "后向儿童座椅装副驾时不要关闭气囊，应开启气囊。"
        self.assertFalse(self.evaluator.factual_text_covers("child.rear_front", bad))

    def test_reversed_forward_facing_warning_does_not_pass_fact_check(self):
        bad = "前向儿童座椅放副驾时禁止开启气囊，应该关闭气囊。"
        self.assertFalse(self.evaluator.factual_text_covers("child.forward_front", bad))

    def test_non_target_window_mutation_fails_even_with_success_message(self):
        engine = Engine()
        before = engine.vehicle()
        result = engine.process("副驾车窗开50%")
        result["vehicle"]["windows"]["rear_left"] = 50
        expected = {"statuses": ["executed"], "tool": "set_window",
                    "args": {"position": "front_right", "percent": 50}}
        self.assertIn("non_target_changed", self.evaluator.judge(expected, result, before))


if __name__ == "__main__":
    unittest.main()
