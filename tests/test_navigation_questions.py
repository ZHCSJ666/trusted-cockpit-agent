"""Workspace domain regressions; all provider responses below are test doubles.

These tests exercise the public runtime and registered production tool schemas.
They establish routing and authorization behavior, not external map quality.
"""
import copy
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cockpit-agent"))

from interview.expanded_engine import ExpandedEngine
from interview.expanded_tests import FakeClient, tool_call
from interview.runtime import run
from interview.services import SERVICE_TOOLS


QUESTION = "帮我查询一下怎么去杭州市政府"
DOCUMENTS = [
    {"id": "ec40-uk", "vehicle": "EC40 2026 UK", "title": "EC40 2026 UK 手册"},
    {"id": "ec40-us", "vehicle": "EC40 2026 US", "title": "EC40 2026 US 手册"},
]


class Services:
    def __init__(self):
        self.calls = []

    def tools(self):
        return copy.deepcopy(SERVICE_TOOLS)

    def snapshot(self, context):
        return {**copy.deepcopy(context), "preferences": [], "documents": copy.deepcopy(DOCUMENTS)}

    async def execute(self, name, args, context):
        self.calls.append((name, copy.deepcopy(args)))
        if name == "search_manual":
            if not args.get("document_id"):
                return {"status": "clarify", "message": "请先选择一份适用的车型、年份和地区手册。",
                        "data": {"documents": copy.deepcopy(DOCUMENTS)}}
            return {"status": "answered", "message": "已检索到测试手册的相关页面。",
                    "data": {"document_id": args["document_id"]}}
        if name == "plan_route":
            if not args.get("destination") and not args.get("candidate_index"):
                return {"status": "clarify", "message": "请告诉我目的地。", "data": {}}
            context["last_route"] = {"destination": {"name": args.get("destination", "候选地点")}}
            return {"status": "executed", "message": "已获得测试路线。", "data": context["last_route"]}
        if name == "get_weather":
            return {"status": "answered", "message": "测试天气：晴。", "data": copy.deepcopy(args)}
        raise AssertionError(f"Unexpected test service call: {name}")


def stale_manual_context():
    """The state left behind by the reported misrouted navigation question."""
    return {"pending_service": {
        "tool": "search_manual", "args": {"query": QUESTION}, "text": QUESTION,
        "question": "请先选择一份适用的车型、年份和地区手册。",
        "data": {"documents": copy.deepcopy(DOCUMENTS)}, "created_at": time.monotonic(),
    }}


async def invoke(text, *, services=None, context=None, client=None, engine=None, **kwargs):
    return await run(engine or ExpandedEngine(), text, services=services or Services(),
                     context=context if context is not None else {}, client=client,
                     history=[], **kwargs)


class NavigationQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_destination_questions_preserve_literal_places_across_cities(self):
        cases = [
            (QUESTION, "杭州市政府"),
            ("请问怎么去南京南站？", "南京南站"),
            ("怎样去成都东站", "成都东站"),
            ("武汉站怎么走", "武汉站"),
            ("我想去苏州博物馆", "苏州博物馆"),
            ("到厦门北站怎么走", "厦门北站"),
            ("帮我查一下到青岛北站的路线", "青岛北站"),
        ]
        for text, destination in cases:
            with self.subTest(text=text):
                services = Services()
                result = await invoke(text, services=services, provider="offline")
                self.assertEqual(result["status"], "executed", result)
                self.assertEqual(services.calls, [("plan_route", {"destination": destination})])

    async def test_missing_destination_asks_for_place_then_completes_same_task(self):
        services, context = Services(), {}
        result = await invoke("帮我查一下怎么去", services=services, context=context, provider="offline")
        self.assertEqual(result["status"], "clarify", result)
        self.assertIn("目的地", result["message"])
        self.assertEqual(services.calls, [("plan_route", {})])
        result = await invoke("杭州市政府", services=services, context=context, provider="offline")
        self.assertEqual(result["status"], "executed", result)
        self.assertEqual(services.calls[-1], ("plan_route", {"destination": "杭州市政府"}))

    async def test_old_misrouted_manual_prompt_does_not_trap_new_navigation(self):
        services, context = Services(), stale_manual_context()
        result = await invoke(QUESTION, services=services, context=context, provider="offline")
        self.assertEqual(result["status"], "executed", result)
        self.assertEqual(services.calls, [("plan_route", {"destination": "杭州市政府"})])
        self.assertNotIn("pending_service", context)

    async def test_real_manual_question_can_be_followed_by_navigation(self):
        services, context = Services(), {}
        first = await invoke("如何安装儿童座椅", services=services, context=context, provider="offline")
        self.assertEqual(first["status"], "clarify", first)
        second = await invoke("武汉站怎么走", services=services, context=context, provider="offline")
        self.assertEqual(second["status"], "executed", second)
        self.assertEqual([name for name, args in services.calls], ["search_manual", "plan_route"])
        self.assertEqual(services.calls[-1][1], {"destination": "武汉站"})

    async def test_vehicle_knowledge_questions_remain_manual_only(self):
        for text in ["如何安装儿童座椅", "胎压是多少", "怎么关闭副驾气囊",
                     "车载导航怎么设置目的地", "怎么去除车窗雾气", "雨刷怎么更换"]:
            with self.subTest(text=text):
                services, engine = Services(), ExpandedEngine()
                result = await invoke(text, services=services, engine=engine, provider="offline")
                self.assertEqual(result["status"], "clarify", result)
                self.assertEqual(services.calls, [("search_manual", {"query": text})])
                self.assertEqual(engine.driver.command_count, 0)

    async def test_document_selection_by_ordinal_or_full_vehicle_still_works(self):
        for reply, selected in [("第二份", "ec40-us"), ("EC40 2026 UK", "ec40-uk")]:
            with self.subTest(reply=reply):
                services, context = Services(), {}
                await invoke("如何安装儿童座椅", services=services, context=context, provider="offline")
                result = await invoke(reply, services=services, context=context, provider="offline")
                self.assertEqual(result["status"], "answered", result)
                self.assertEqual(services.calls[-1], ("search_manual", {
                    "query": "如何安装儿童座椅", "document_id": selected}))

    async def test_invalid_document_ordinal_stays_a_document_clarification(self):
        services, context = Services(), {}
        await invoke("如何安装儿童座椅", services=services, context=context, provider="offline")
        result = await invoke("第八份", services=services, context=context, provider="offline")
        self.assertEqual(result["status"], "clarify", result)
        self.assertEqual(len(services.calls), 1)
        self.assertIn("pending_service", context)

    async def test_generic_how_questions_reach_planner_without_forced_manual(self):
        for text in ["怎么做番茄炒蛋", "如何使用这个项目"]:
            with self.subTest(text=text):
                services = Services()
                client = FakeClient([tool_call("ask_clarification", question="想了解哪一方面？")])
                result = await invoke(text, services=services, client=client)
                self.assertEqual(result["status"], "clarify", result)
                self.assertEqual(result["message"], "想了解哪一方面？")
                self.assertTrue(client.messages)
                self.assertFalse(services.calls)

    async def test_new_generic_question_can_leave_pending_manual(self):
        services, context = Services(), stale_manual_context()
        client = FakeClient([tool_call("ask_clarification", question="想了解哪一方面？")])
        result = await invoke("如何使用这个项目", services=services, context=context, client=client)
        self.assertEqual(result["message"], "想了解哪一方面？")
        self.assertTrue(client.messages)
        self.assertFalse(services.calls)
        self.assertNotIn("pending_service", context)

    async def test_compound_question_keeps_route_and_weather_tasks(self):
        services = Services()
        client = FakeClient([
            tool_call("plan_route", destination="杭州市政府"),
            tool_call("get_weather", location="杭州"),
        ], [tool_call("finish", message="")])
        result = await invoke(QUESTION + "，然后查杭州天气", services=services, client=client)
        self.assertIn(result["status"], {"executed", "answered"}, result)
        self.assertEqual(services.calls, [
            ("plan_route", {"destination": "杭州市政府"}),
            ("get_weather", {"location": "杭州"}),
        ])
        self.assertTrue(client.messages)

    async def test_planner_cannot_shorten_replace_or_omit_explicit_destination(self):
        for args in [{"destination": "杭州"}, {"destination": "南京市政府"}, {}, {"candidate_index": 1}]:
            with self.subTest(args=args):
                services = Services()
                client = FakeClient([tool_call("plan_route", **args)])
                context = {"places": [{"id": "node/other", "name": "另一处地点"}]}
                result = await invoke(QUESTION + "，然后查杭州天气", services=services, client=client, context=context)
                self.assertEqual(result["status"], "blocked", result)
                self.assertFalse(services.calls)

    async def test_negated_or_hypothetical_question_does_not_directly_plan_route(self):
        for text in ["不要帮我查询怎么去杭州市政府", "如果我想去杭州市政府，你能规划吗"]:
            with self.subTest(text=text):
                services, engine = Services(), ExpandedEngine()
                client = FakeClient([tool_call("ask_clarification", question="需要现在规划路线吗？")])
                result = await invoke(text, services=services, client=client, engine=engine)
                self.assertNotEqual(result["status"], "executed", result)
                self.assertFalse(services.calls)
                self.assertEqual(engine.driver.command_count, 0)

    async def test_non_driving_question_does_not_silently_become_driving(self):
        services = Services()
        client = FakeClient([tool_call("report_unsupported", reason="当前路线服务仅支持驾车路线。")])
        result = await invoke("我想步行去杭州市政府", services=services, client=client)
        self.assertEqual(result["status"], "unsupported", result)
        self.assertFalse(services.calls)


if __name__ == "__main__":
    unittest.main()
