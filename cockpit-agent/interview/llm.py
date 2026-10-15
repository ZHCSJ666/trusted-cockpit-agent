"""Server-only Kimi adapter. Credentials are read in memory, never persisted."""
from __future__ import annotations

import asyncio
import json
import os
import time

import httpx

from .config import ROOT as OUT, ConfigurationError, api_credentials, load_project_env


class ModelError(RuntimeError):
    pass


class KimiClient:
    def __init__(self, credential_path=None):
        self._config_error = None
        try:
            load_project_env()
        except ConfigurationError as exc:
            self._config_error = str(exc)
        self.path = credential_path
        self.model = os.getenv("COCKPIT_MODEL", "").strip()
        self.report = {"available": False, "name": self.model or "Kimi", "status": "not_checked"}
        self._client = None
        self._lock = asyncio.Lock()
        self.models = []
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def connect(self):
        async with self._lock:
            if self._client is not None:
                return
            client = None
            try:
                if self._config_error:
                    raise ConfigurationError(self._config_error)
                credentials = api_credentials(self.path)
                client = httpx.AsyncClient(base_url=credentials.base_url, headers={"Authorization": "Bearer " + credentials.key},
                                           timeout=httpx.Timeout(90, connect=10), trust_env=False)
                r = await client.get("models")
                if r.status_code != 200:
                    raise ModelError(f"模型目录不可用（HTTP {r.status_code}）。")
                data = r.json().get("data", [])
                if not isinstance(data, list) or any(not isinstance(m, dict) or not isinstance(m.get("id"), str) for m in data):
                    raise ModelError("模型目录返回格式无效。")
                ids = [m["id"] for m in data]
                self.models = ids
                if not self.model:
                    self.model = next((m for m in ids if "kimi" in m.lower()), "")
                if not self.model or self.model not in ids:
                    raise ModelError("COCKPIT_MODEL 不在模型目录中，或未指定模型且目录中没有 Kimi。")
                self._client = client
                self.report = {"available": True, "name": self.model, "status": "ready"}
            except ConfigurationError as exc:
                self.report = {"available": False, "name": self.model or "Kimi", "status": "unavailable"}
                raise ModelError(str(exc)) from None
            except ModelError:
                self.report = {"available": False, "name": self.model or "Kimi", "status": "unavailable"}
                raise
            except Exception:
                self.report = {"available": False, "name": self.model or "Kimi", "status": "unavailable"}
                raise ModelError("无法读取凭据或连接模型服务；可使用离线规则模式。") from None
            finally:
                if client is not None and self._client is not client:
                    await client.aclose()

    async def request(self, messages, tools=None, temperature=0.2, *, model=None, max_tokens=1400, tool_choice="auto"):
        await self.connect()
        selected = model or self.model
        if selected not in self.models:
            raise ModelError("所选模型不在当前服务目录中。")
        payload = {"model": selected, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            payload.update(tools=tools, tool_choice=tool_choice)
        start = time.monotonic()
        for attempt in range(2):
            try:
                r = await self._client.post("chat/completions", json=payload)
            except httpx.HTTPError:
                raise ModelError("模型调用超时或连接失败；未下发新的车辆动作。") from None
            if r.status_code in (429, 502, 503) and attempt == 0:
                await asyncio.sleep(1)
                continue
            if r.status_code != 200:
                raise ModelError(f"模型调用失败（HTTP {r.status_code}）；未下发新的车辆动作。")
            try:
                data = r.json()
                message = data["choices"][0]["message"]
                usage = data.get("usage") or {}
                for k in self.usage:
                    self.usage[k] += int(usage.get(k, 0) or 0)
                # Provider reasoning fields deliberately excluded from traces and saved artifacts.
                return {"content": message.get("content") or "", "tool_calls": message.get("tool_calls") or [],
                        "finish_reason": data["choices"][0].get("finish_reason"),
                        "model": data.get("model", selected), "usage": usage,
                        "latency_ms": round((time.monotonic()-start)*1000, 1)}
            except (KeyError, ValueError, IndexError, TypeError):
                raise ModelError("模型返回格式不完整；未执行车辆动作。") from None

    async def plan(self, text: str, vehicle: dict, context: list | None = None):
        from .engine import TOOLS
        tool_list = [t for t in TOOLS if vehicle.get("profile") == "premium" or t["function"]["name"] != "set_seat_massage"]
        for name, desc, prop in [
            ("ask_clarification", "必要信息不足时向用户询问，不能猜测执行对象、位置或数值。", "question"),
            ("lookup_manual", "查询车辆说明书，包括儿童座椅、胎压、安全警告和维修问题。", "query"),
            ("report_unsupported", "车辆缺少能力或工具时明确告知。", "reason"),
            ("reply", "一般交流或说明支持功能，不宣称执行过动作。", "message"),
        ]:
            tool_list.append({"type": "function", "function": {"name": name, "description": desc,
                "parameters": {"type": "object", "properties": {prop: {"type": "string"}}, "required": [prop], "additionalProperties": False}}})
        system = (
            "你是面试项目中的模拟车载规划器。通过工具提出计划，工具调用尚未执行，禁止预先宣称成功。"
            "车辆为左舵模拟车，副驾=front_right，主驾=front_left。只处理用户明确授权的单个目标；"
            "多个不同动作请先澄清优先项。关键对象、位置、开度缺失时可查给定对话上下文，仍不唯一就询问。"
            "开到50%是绝对开度，打开/关闭分别为100/0；'开一点'缺少数值，不能任意设定。"
            "无法实现的功能要说明不支持。说明书问句用lookup_manual，不把知识问题当车控。"
            "运动中的车门/后备箱动作不安全。温度允许16..30°C。信息仅来自下方模拟观测和对话。"
        )
        messages = [{"role": "system", "content": system + "\n模拟车辆：" + json.dumps(vehicle, ensure_ascii=False)}]
        for turn in (context or [])[-6:]:
            messages.extend([{"role": "user", "content": turn["text"]}, {"role": "assistant", "content": turn["message"]}])
        messages.append({"role": "user", "content": text})
        r = await self.request(messages, tool_list)
        calls = r["tool_calls"]
        if len(calls) > 1:
            proposal = {"kind": "clarify", "question": "这句话涉及多个动作，请先指定要执行哪一个。"}
        elif calls:
            try:
                name = calls[0]["function"]["name"]
                args = json.loads(calls[0]["function"]["arguments"])
                if not isinstance(args, dict):
                    raise ValueError()
            except (KeyError, ValueError, TypeError):
                raise ModelError("模型工具参数不是合法 JSON 对象；已停止执行。") from None
            if name == "ask_clarification":
                proposal = {"kind": "clarify", "question": args.get("question", "请补充具体对象和参数。")}
            elif name == "lookup_manual":
                proposal = {"kind": "manual", "query": args.get("query", text)}
            elif name == "report_unsupported":
                proposal = {"kind": "unsupported", "message": args.get("reason", "该车型不支持此能力。")}
            elif name == "reply":
                proposal = {"kind": "chat", "message": args.get("message", "")}
            else:
                proposal = {"kind": "action", "tool": name, "args": args}
        else:
            # Free text is never an execution receipt, even if the model says "done".
            proposal = {"kind": "clarify", "question": "模型没有提出可验证的工具计划，请补充具体操作对象和参数。"}
        return proposal, {k: v for k, v in r.items() if k not in ("content", "tool_calls")}

    async def draft(self, query, evidence):
        content = json.dumps([{k: c[k] for k in ("id", "title", "text", "conditions")} for c in evidence], ensure_ascii=False)
        return await self.request([
            {"role": "system", "content": "你是车辆说明书助手。只依据给定资料回答，保留车型、位置、朝向、安全警告和适用条件。使用[id]引用；证据不足时说明不足。"},
            {"role": "user", "content": "问题：" + query + "\n资料：" + content},
        ])

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
