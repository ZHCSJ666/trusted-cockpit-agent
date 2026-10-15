"""Regression for natural chat vs service buttons; provider data is fake here."""
import copy
import json
from pathlib import Path
import sys
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cockpit-agent"))
from interview.chat_intents import explicit_route, news_request
from interview.expanded_engine import ExpandedEngine
from interview.expanded_tests import FakeServices, tool_call
from interview.llm import KimiClient
from interview.runtime import run, _service_authority
from interview.services import SERVICE_TOOLS


ROUTE = "从杭州西湖出发，到杭州东站，帮我规划驾车路线"
NEWS = "给我查一下今天有什么新闻"


class Services(FakeServices):
    def tools(self):
        return [t for t in super().tools() if t["function"]["name"] != "get_news"] + [
            t for t in SERVICE_TOOLS if t["function"]["name"] == "get_news"]


class Client:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    async def request(self, messages, **options):
        self.requests.append({"messages": copy.deepcopy(messages), **options})
        if not self.replies:
            raise AssertionError("Unplanned model call")
        return self.replies.pop(0)


async def invoke(text, services=None, client=None, **kwargs):
    return await run(ExpandedEngine(), text, services=services or Services(), client=client,
                     context=kwargs.pop("context", {}), history=kwargs.pop("history", []), **kwargs)


class ChatRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_route_and_paraphrases_keep_endpoint_roles(self):
        for text in [ROUTE, "帮我规划从杭州西湖到杭州东站的驾车路线", "我想从杭州西湖到杭州东站",
                     "请从杭州西湖到杭州东站规划路线"]:
            with self.subTest(text=text):
                s, c = Services(), Client()
                r = await invoke(text, services=s, client=c)
                self.assertEqual(r["status"], "executed", r)
                self.assertEqual(s.calls, [("plan_route", {"origin": "杭州西湖", "destination": "杭州东站"})])
                self.assertFalse(c.requests)

    async def test_exact_news_and_paraphrases_query_real_service_contract(self):
        for text, args in [(NEWS, {"period": "today"}), ("今天有哪些新闻？", {"period": "today"}),
                           ("帮我看看最新汽车新闻", {"topic": "汽车"}),
                           ("今天的科技新闻", {"topic": "科技", "period": "today"})]:
            with self.subTest(text=text):
                s, c = Services(), Client()
                r = await invoke(text, services=s, client=c)
                self.assertEqual(r["status"], "answered", r)
                self.assertEqual(s.calls, [("get_news", args)])
                self.assertFalse(c.requests)

    async def test_previous_failed_conversation_cannot_poison_explicit_request(self):
        s = Services()
        r = await invoke(NEWS, services=s, client=Client(), history=[
            {"text": NEWS, "message": "模型没有提供可验证的工具计划，请说明具体地点、设备或查询内容。"}])
        self.assertEqual(r["status"], "answered")
        self.assertEqual(s.calls, [("get_news", {"period": "today"})])

    async def test_ambiguous_origin_keeps_destination_on_followup(self):
        class Ambiguous(Services):
            async def execute(self, name, args, context):
                if name == "plan_route" and args.get("origin") == "杭州西湖":
                    self.calls.append((name, copy.deepcopy(args)))
                    context["places"] = [{"id": "node/111", "name": "西湖入口甲"}, {"id": "node/222", "name": "西湖入口乙"}]
                    return {"status": "clarify", "message": "起点有多个匹配，请选择。", "data": {"places": context["places"]}}
                return await super().execute(name, args, context)
        s, context = Ambiguous(), {}
        self.assertEqual((await invoke(ROUTE, services=s, context=context))["status"], "clarify")
        r = await invoke("第二个", services=s, context=context)
        self.assertEqual(r["status"], "executed", r)
        self.assertEqual(s.calls[-1], ("plan_route", {"origin": "node/222", "destination": "杭州东站"}))

    def test_shortcuts_do_not_swallow_compound_negative_or_hypothetical_requests(self):
        for text in [ROUTE + "，并把空调设为22度", "不要从杭州西湖到杭州东站规划路线",
                     "如果从杭州西湖到杭州东站，应该怎么规划", "如何实现从杭州西湖到杭州东站的导航",
                     "从杭州西湖到杭州东站不需要规划路线", "从杭州西湖到杭州东站要多久",
                     "从杭州西湖到杭州东站再调温度22度",
                     "从杭州西湖到杭州东站，途经博物馆", "从杭州西湖到杭州东站的步行路线"]:
            self.assertIsNone(explicit_route(text), text)
        for text in [NEWS + "，然后打开车窗", "不要给我查新闻", "新闻是什么", "如果今天有新闻就播报"]:
            self.assertIsNone(news_request(text), text)

    def test_swapped_or_missing_explicit_origin_rejected(self):
        for args in [{"destination": "杭州东站"}, {"origin": "杭州东站", "destination": "杭州西湖"},
                     {"origin": "杭州", "destination": "杭州东站"}, {"candidate_index": 1}]:
            self.assertIsNotNone(_service_authority("plan_route", args, ROUTE, {}), args)
            self.assertIsNotNone(_service_authority("plan_route", args, ROUTE + "，并把空调设为22度", {}), args)

    async def test_empty_plan_repaired_once_without_trusting_prose(self):
        s = Services()
        c = Client({"content": "已经查到新闻，还打开了车窗", "tool_calls": []},
                   {"tool_calls": [tool_call("get_news", topic="汽车")]}, {"tool_calls": []})
        r = await invoke("请给我汽车行业资讯", services=s, client=c)
        self.assertEqual(r["status"], "answered", r)
        self.assertEqual(s.calls, [("get_news", {"topic": "汽车"})])
        self.assertEqual(c.requests[1]["tool_choice"], "required")
        self.assertNotIn("已经查到新闻，还打开了车窗", json.dumps(c.requests[1]["messages"], ensure_ascii=False))
        self.assertEqual(r["vehicle"]["windows"], {"front_left": 0, "front_right": 0, "rear_left": 0, "rear_right": 0})

    async def test_repeated_empty_plan_is_service_failure_not_missing_user_input(self):
        c, s = Client({"tool_calls": []}, {"tool_calls": []}), Services()
        r = await invoke("请给我汽车行业资讯", services=s, client=c)
        self.assertEqual(r["status"], "unavailable")
        self.assertTrue(r["model_error"])
        self.assertEqual(len(c.requests), 2)
        self.assertFalse(s.calls)

    async def test_greeting_plus_task_cannot_bypass_plan_repair(self):
        c = Client({"content": "你可以在信息服务页面查看新闻", "tool_calls": []},
                   {"tool_calls": [tool_call("get_news", period="today")]}, {"tool_calls": []})
        s = Services()
        r = await invoke("你好，" + NEWS, client=c, services=s)
        self.assertEqual(r["status"], "answered")
        self.assertEqual(s.calls, [("get_news", {"period": "today"})])
        self.assertEqual(c.requests[1]["tool_choice"], "required")

    async def test_repair_still_checks_original_control_authorization(self):
        c = Client({"tool_calls": []}, {"tool_calls": [tool_call("set_window", position="front_right", percent=50)]})
        r = await invoke("请给我汽车行业资讯", client=c)
        self.assertEqual(r["status"], "blocked", r)
        self.assertFalse(r["calls"])

    async def test_repaired_clarification_remains_a_real_question(self):
        c = Client({"tool_calls": []}, {"tool_calls": [tool_call("ask_clarification", question="想搜索哪座城市的咖啡店？")]})
        r = await invoke("找一个合适的地方休息", client=c)
        self.assertEqual(r["status"], "clarify")
        self.assertEqual(r["message"], "想搜索哪座城市的咖啡店？")

    async def test_completed_tool_not_retried_when_final_prose_has_no_tools(self):
        c = Client({"tool_calls": [tool_call("get_news")]}, {"tool_calls": [], "content": "完成了"})
        s = Services()
        r = await invoke("请给我汽车行业资讯", services=s, client=c)
        self.assertEqual(r["status"], "answered")
        self.assertEqual(len(s.calls), 1)
        self.assertEqual(len(c.requests), 2)

    async def test_adapter_preserves_default_and_passes_explicit_required_choice(self):
        payloads = []
        def transport(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [tool_call("get_news")]}}]})
        c = KimiClient()
        c.model, c.models = "test", ["test"]
        c._client = httpx.AsyncClient(base_url="https://model.invalid/v1/", transport=httpx.MockTransport(transport))
        try:
            await c.request([], tools=Services().tools())
            r = await c.request([], tools=Services().tools(), tool_choice="required")
            self.assertEqual([p["tool_choice"] for p in payloads], ["auto", "required"])
            self.assertEqual(r["finish_reason"], "tool_calls")
        finally:
            await c.close()
