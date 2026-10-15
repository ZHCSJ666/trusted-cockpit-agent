"""Deterministic, inspectable controls around an untrusted planning model.

All physical effects are SIMULATED. Commands enter the upstream VAL.execute;
InterviewVAL extends only its simulator with per-position windows and physical
doors. A door opening is a demo-specific physical-door simulation in addition to
the upstream lock operation, never inferred solely from an unlock receipt.

``baseline`` means a deliberately simplified teaching control. It is NOT the
complete upstream application and its results cannot measure upstream quality.
The in-memory operation/confirmation ledgers do not survive process restart.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import secrets
import time
from typing import Any

from jsonschema import Draft202012Validator

from orchestrator.edge.val import VAL
from orchestrator.edge.vehicle_driver import SimulatedVehicleDriver
from runtime.positions import ids_of, scan_positions

POSITIONS = ("front_left", "front_right", "rear_left", "rear_right")
LABELS = dict(zip(POSITIONS, ("主驾", "副驾", "左后", "右后")))
FAULTS = {"none", "wrong_target", "timeout_after_apply", "stale_state"}


def _tool(name, description, properties):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": list(properties), "additionalProperties": False}}}


TOOLS = [
    _tool("set_window", "设置指定模拟车窗的绝对开度，不能猜测位置或百分比。", {
        "position": {"type": "string", "enum": list(POSITIONS)},
        "percent": {"type": "integer", "minimum": 0, "maximum": 100}}),
    _tool("set_temperature", "设置模拟车内空调温度，摄氏度。", {
        "celsius": {"type": "integer", "minimum": 16, "maximum": 30}}),
    _tool("set_door", "演示适配器的实体车门模拟；不同于仅解除门锁，须停车P挡并确认。", {
        "position": {"type": "string", "enum": list(POSITIONS)},
        "open": {"type": "boolean"}}),
    _tool("set_trunk", "打开或关闭模拟后备箱，须停车P挡并确认。", {
        "open": {"type": "boolean"}}),
    _tool("set_seat_massage", "设置模拟按摩开关；仅premium车型提供。", {
        "enabled": {"type": "boolean"}}),
    _tool("navigate", "仅建立本地模拟导航目的地，不声称真实地图路线已经获取。", {
        "destination": {"type": "string", "minLength": 1, "maxLength": 120}}),
]
REGISTRY = {t["function"]["name"]: t["function"] for t in TOOLS}
VALIDATORS = {name: Draft202012Validator(t["parameters"]) for name, t in REGISTRY.items()}
OBJECTS = {"set_window": "window", "set_temperature": "aircon", "set_door": "door_lock",
           "set_trunk": "trunk", "set_seat_massage": "seat"}


def _plan(kind="action", tool=None, args=None, **extra):
    return {"kind": kind, "tool": tool, "args": args or {}, **extra}


def _number(text):
    digits = re.search(r"(?<![\d.])-?\d+(?:\.\d+)?", text)
    if digits:
        n = float(digits.group())
        return int(n) if n.is_integer() else n
    match = re.search(r"百分之([零一二两三四五六七八九十百]+)", text)
    if not match:
        match = re.search(r"([零一二两三四五六七八九十百]+)\s*度", text)
    if match:
        value = match.group(1)
        nums = {c: i for i, c in enumerate("零一二三四五六七八九")}
        nums["两"] = 2
        if value == "一百":
            return 100
        if "十" in value:
            left, right = value.split("十", 1)
            return nums.get(left, 1) * 10 + nums.get(right, 0)
        return nums.get(value)
    return None


def _previous(context):
    context = context or {}
    return context.get("pending_plan") or context.get("plan") or (
        context if context.get("tool") in REGISTRY else {})


def _is_state_query(text):
    """Read-vs-write admission for the limited signals this demo can observe.

    Interrogative punctuation alone is not a read: polite imperatives such as
    '能帮我开到50%吗' still authorize an action. Conversely '已经打开了吗'
    cannot authorize opening merely because it contains the word '打开'.
    """
    domain = re.search(r"车窗|窗户|空调|温度|车门|门锁|后备箱|尾门|按摩|车速|档位|挡位|车辆状态|车况", text)
    if not domain:
        return False
    explicit_read = re.search(r"查询|查看|读一下|(?:告诉我|看看).*(?:状态|多少|是否|现在|当前|开没|关没)", text)
    if explicit_read:
        return True
    explicit_action = re.search(r"(?:帮我|替我|给我|请把|请将|麻烦你|能否|能不能).{0,20}(?:打开|关闭|开到|关到|调到|设置|设为|开启|停止)", text)
    if explicit_action:
        return False
    direct_query = re.search(r"开没开|关没关|是否|是不是|有没有|(?:打开|关闭|开|关|锁|启用)(?:着|了|好)?(?:了)?[吗嘛]", text)
    temporal_query = re.search(r"(?:现在|当前|已经|目前|此刻).*(?:[吗嘛?？]|多少|几度|开度|状态)", text)
    numeric_query = re.search(r"(?:车速|档位|挡位|温度|开度)(?:现在|当前|是|为|有|到底|\s){0,3}(?:多少|几|什么)", text)
    return bool(direct_query or temporal_query or numeric_query)


def offline_plan(text: str, context: dict | None = None) -> dict:
    """Conservative Chinese demo parser; no model or vehicle action occurs here.

    Only explicit words or a single recent pending/successful turn provide slots.
    A unique currently-open window is NOT sufficient evidence of user intent.
    Unrecognised formulations ask for clarification instead of guessing.
    """
    text = str(text or "").strip()
    context = context or {}
    prior = _previous(context)
    if _is_state_query(text) and not re.search(r"儿童|婴儿|宝宝|气囊|说明书|如果|假如|假设|安全吗", text):
        return _plan("state", query=text)
    if re.search(r"如何|怎么|怎样|说明书|安装|ISOFIX|气囊|胎压|轮胎|冷却|充电|儿童座椅|婴儿座椅|安全警告|扭矩|牵引重量", text, re.I):
        return _plan("manual", query=text)
    if re.search(r"如果|假如|假设|是否|是不是|开着吗|关着吗|为什么|安全吗", text):
        return _plan("manual", query=text)
    if re.search(r"不要|别(?:给我|帮我|再)?(?:开|关|执行|操作)|取消|不需要", text):
        return _plan("chat", question="已取消，本轮没有执行车辆动作。")
    if not text or text in {"你好", "您好", "hello", "hi", "谢谢", "你是谁"}:
        return _plan("chat")

    kinds = []
    for tool, pattern in (("set_window", r"车窗|窗户"), ("set_temperature", r"空调|温度"),
                          ("set_door", r"车门|门锁"), ("set_trunk", r"后备箱|尾门"),
                          ("set_seat_massage", r"按摩"), ("navigate", r"导航|带我去")):
        if re.search(pattern, text):
            kinds.append(tool)
    if len(kinds) > 1:
        return _plan("clarify", question="这一轮包含多种操作，请先指定一项操作及其参数。")
    if re.search(r"天窗|自动驾驶|弹射|香氛|座椅加热|无人驾驶|支付|付款|加装|变成", text):
        return _plan("unsupported", question="本演示没有注册这项能力，未执行车辆动作。")

    tool = kinds[0] if kinds else None
    # Only a short follow-up explicitly referring to prior context can inherit it.
    followup = bool(re.search(r"再|它|那个|刚才|还是|改成|调到|^\s*(?:开|关|\d)", text)
                    or scan_positions(text))
    if not tool and prior.get("tool") and followup:
        tool = prior["tool"]
    if not tool:
        unsupported_object = re.search(r"(?:打开|开启|启用|启动|关闭|停止)([^，。！？]+)", text)
        if unsupported_object and not re.search(r"一点|一些|那个|这个|它|一半|百分|%", unsupported_object.group(1)):
            return _plan("unsupported", question="没有找到对应的注册能力，未执行车辆动作。")
        if re.search(r"开|关|调|一点|一半|百分|%|副驾|主驾", text):
            return _plan("clarify", question="您想操作什么设备？请说明对象、位置和目标值。")
        return _plan("chat")

    is_pending = bool(context.get("pending_plan"))
    same = prior.get("tool") == tool
    args = copy.deepcopy(prior.get("args", {})) if same and is_pending else {}
    sources = {k: "confirmed_dialog_context" for k in args}
    positions = list(dict.fromkeys(p for word in scan_positions(text) for p in ids_of(word)))
    # Canonical and common English locations are also usable in model experiments.
    for p in POSITIONS:
        if p in text and p not in positions:
            positions.append(p)
    if not positions and re.search(r"passenger", text, re.I):
        positions = ["front_right"]
    ambiguous_position = len(positions) > 1 or (positions and positions[0] not in POSITIONS)
    if ambiguous_position:
        args.pop("position", None)
    elif positions:
        args["position"] = positions[0]
        sources["position"] = "utterance"
    elif tool in {"set_window", "set_door"} and same and followup and prior.get("args", {}).get("position"):
        args["position"] = prior["args"]["position"]
        sources["position"] = "confirmed_dialog_context"

    number = _number(text)
    closing = bool(re.search(r"关闭|关上|关掉|关严|锁上|停用|停止|^关|关(?:车窗|车门|后备箱)", text))
    opening = bool(re.search(r"打开|开启|启用|启动|开到|开成|开大|全开|开(?:\s|\d|一半|一点|百分|车窗|车门)|^开", text))
    if tool == "set_window":
        if closing:
            args["percent"] = 0
            sources["percent"] = "utterance:close=0"
        elif number is not None:
            relative = bool(re.search(r"再(?:给我)?开|增加|增大|减少|再关", text)) and "到" not in text
            if relative:
                p = args.get("position")
                current = context.get("vehicle", {}).get("windows", {}).get(p)
                if current is None and same:
                    current = prior.get("args", {}).get("percent")
                if current is None:
                    return _plan("clarify", tool, args, question="请给出绝对目标开度；当前开度没有可靠上下文。")
                sign = -1 if re.search(r"减少|再关", text) else 1
                args["percent"] = current + sign * number
                sources["percent"] = "utterance_delta+simulated_state"
            else:
                args["percent"] = number
                sources["percent"] = "utterance"
        elif "一半" in text or "半开" in text:
            args["percent"] = 50
            sources["percent"] = "utterance:half=50"
        elif re.search(r"一点|一些|稍微|大点|小点", text):
            args.pop("percent", None)
            sources.pop("percent", None)
        elif opening:
            args["percent"] = 100
            sources["percent"] = "utterance:open=100"
    elif tool == "set_temperature":
        args.pop("position", None)
        if number is not None:
            args["celsius"] = number
            sources["celsius"] = "utterance"
    elif tool in {"set_door", "set_trunk", "set_seat_massage"}:
        key = "enabled" if tool == "set_seat_massage" else "open"
        if opening or closing or ("开" in text and not re.search(r"开关|开着吗", text)):
            args[key] = not closing
            sources[key] = "utterance"
        if tool != "set_door":
            args.pop("position", None)
    elif tool == "navigate":
        args.pop("position", None)
        destination = re.sub(r"^.*?(?:导航(?:到|去)?|带我去)\s*", "", text).strip(" ，。！？")
        unresolved = bool(re.search(r"那里|这里|那儿|这儿|常去|老地方|那个地方|^家$|^公司$", destination))
        if destination and destination != text and not unresolved:
            args["destination"] = destination
            sources["destination"] = "utterance"

    required = REGISTRY[tool]["parameters"]["required"]
    missing = [key for key in required if key not in args]
    if ambiguous_position:
        return _plan("clarify", tool, args, question="请指定一扇车窗或一扇车门，例如副驾或右后。",
                     slot_sources=sources)
    if missing:
        question = "请补充" + "、".join({"position": "具体位置（主驾/副驾/左后/右后）",
                    "percent": "车窗目标开度（0–100%）", "celsius": "目标温度（16–30℃）",
                    "open": "打开还是关闭", "enabled": "开启还是关闭按摩",
                    "destination": "导航目的地"}[k] for k in missing) + "。"
        return _plan("clarify", tool, args, question=question, slot_sources=sources)
    return _plan("action", tool, args, slot_sources=sources)


class InterviewDriver(SimulatedVehicleDriver):
    """Faults enter only this local simulated-driver adapter, never a real tool."""

    def __init__(self, fault="none"):
        super().__init__(vehicle_id="interview-simulator")
        self.fault = fault
        self.observed_at = time.monotonic()
        self.records = {}
        for p in POSITIONS:
            self.state[f"window_{p}"] = 0
            self.state[f"physical_door_{p}"] = False
        if fault == "timeout_after_apply":
            self.set_faults(lose_next_ack=1)
        if fault == "stale_state":
            self.observed_at -= 60

    def dispatch(self, operation_id, command, val, confirmed=False):
        actual = copy.deepcopy(command)
        if self.fault == "wrong_target" and actual["data"].get("object") == "window":
            position = actual["data"].get("positions", ["front_right"])[0]
            actual["data"]["positions"] = ["rear_right" if position != "rear_right" else "front_right"]
        outcome = {}

        def execute():
            outcome["ok"], outcome["message"] = val.execute(actual, confirmed=confirmed)
            return outcome["ok"], outcome["message"]

        receipt = self.run_once(operation_id, execute)
        record = {"operation_id": operation_id, "receipt": receipt.status,
                  "acknowledgement_received": receipt.acknowledgement_received,
                  "ok": outcome.get("ok", False), "message": outcome.get("message", ""),
                  "actual_command": actual, "source": "simulated"}
        self.records[operation_id] = record
        # State age is supplied by this simulation; reading does not refresh stale data.
        if self.fault != "stale_state":
            self.observed_at = time.monotonic()
        return copy.deepcopy(record)


class InterviewVAL(VAL):
    """Keep upstream control gates; extend only the local simulation of effects."""

    def _simulate(self, obj, operate, data):
        result = super()._simulate(obj, operate, data)
        if obj == "window":
            for position in data.get("positions", []):
                self.state[f"window_{position}"] = 0 if operate == "close" else int(data.get("value", 100))
        elif obj == "door_lock" and data.get("interview_physical_door") is True:
            # Explicit simulator extension. An ordinary upstream unlock never does this.
            for position in data.get("positions", []):
                self.state[f"physical_door_{position}"] = operate == "open"
        return result


class Engine:
    """One local session. Callers must serialize access to a given instance."""

    def __init__(self, profile="standard", speed=0, gear="P", fault="none"):
        self.reset(profile, speed, gear, fault)

    def reset(self, profile="standard", speed=0, gear="P", fault="none"):
        if profile not in {"standard", "premium"} or fault not in FAULTS:
            raise ValueError("invalid_simulator_profile_or_fault")
        if type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 250:
            raise ValueError("invalid_simulated_speed")
        if gear not in {"P", "N", "D", "R", "S"}:
            raise ValueError("invalid_simulated_gear")
        self.profile, self.fault = profile, fault
        self.revision = 0
        self.driver = InterviewDriver(fault)
        self.val = InterviewVAL(driver=self.driver, on_change=self._on_change)
        self.val.set_env("gear", gear)
        self.val.set_env("speed_kmh", speed)
        self.permissions = set(REGISTRY)
        # Offline experiment switch only. The HTTP API must not accept this field.
        self.disabled_guards = set()
        self.context = {}
        self.pending = None
        self._used_tokens = set()
        self.navigation_destination = None
        return self.vehicle()

    def _on_change(self, changes):
        self.revision += 1

    def sample_state(self):
        """Explicitly sample local simulated sensors; a stale fault stays stale.

        Unlike vehicle(), this represents a new sample from the in-process source.
        Server callers invoke it separately so model latency cannot silently turn
        a read of an old cache into fresh evidence.
        """
        if self.driver.fault != "stale_state":
            self.driver.observed_at = time.monotonic()
        return self.vehicle()

    def vehicle(self):
        state = self.val.state
        return {"speed": state.get("speed_kmh"), "gear": state.get("gear"),
                "windows": {p: state.get(f"window_{p}", 0) for p in POSITIONS},
                "temperature": state.get("hvac_temp"),
                "doors": {p: state.get(f"physical_door_{p}", False) for p in POSITIONS},
                "trunk_open": state.get("trunk") == "open", "massage": bool(state.get("seat_massage", False)),
                "profile": self.profile, "source": "simulated", "revision": self.revision,
                "navigation_destination": self.navigation_destination,
                "state_age_ms": round((time.monotonic() - self.driver.observed_at) * 1000)}

    def capabilities(self):
        return [copy.deepcopy(t) for t in TOOLS
                if t["function"]["name"] != "set_seat_massage" or self.profile == "premium"]

    @staticmethod
    def _trace(trace, stage, status, detail):
        trace.append({"stage": stage, "status": status, "detail": detail})

    def _result(self, status, message, plan, trace, calls=None, **extra):
        if status in {"blocked", "unsupported", "failed", "answered"}:
            self.context = {}
        return {"status": status, "message": message, "vehicle": self.vehicle(), "trace": trace,
                "calls": calls or [], "evidence": [], "plan": copy.deepcopy(plan),
                "source": "simulated", **extra}

    def _safety_error(self, plan):
        if time.monotonic() - self.driver.observed_at > 10:
            return "车态观测已过期；更新车态后才能执行。"
        state = self.vehicle()
        if not self.driver.inputs_available({"speed_kmh", "gear", "child_lock", "battery"}):
            return "安全所需车辆信号不可用，已阻止执行。"
        tool, args = plan.get("tool"), plan.get("args", {})
        if tool in {"set_door", "set_trunk"} and (state["speed"] != 0 or state["gear"] != "P"):
            return "车门/后备箱操作要求车速为0且处于P挡；用户确认也不能绕过此规则。"
        if tool == "set_window" and state["speed"] > 80:
            p = args.get("position")
            if args.get("percent", 100) > state["windows"].get(p, 0):
                return "高速行驶时禁止增加车窗开度。"
        if state["gear"] == "R" and tool != "navigate":
            return "倒车期间暂停非必要车控，请专注驾驶。"
        return None

    def _requires_confirmation(self, tool):
        obj = OBJECTS.get(tool)
        return bool(obj and self.val.commands.get("objects", {}).get(obj, {}).get("require_confirm"))

    def process(self, text, plan=None, mode="guarded"):
        if mode not in {"guarded", "baseline"}:
            raise ValueError("invalid_mode")
        trace = []
        self._trace(trace, "input", "ok", "原话用于授权；模型计划只作为候选。")
        expected = offline_plan(text, {**self.context, "vehicle": self.vehicle()})
        proposed = copy.deepcopy(plan if plan is not None else expected)
        if not isinstance(proposed, dict) or not isinstance(proposed.get("args", {}), dict):
            return self._result("failed", "模型计划格式错误，未执行。", {}, trace)
        if self.pending:
            self._used_tokens.add(self.pending["token"])
            self.pending = None

        guarded = mode == "guarded"
        active = lambda name: guarded and name not in self.disabled_guards
        if self.disabled_guards:
            self._trace(trace, "ablation", "warning", {"disabled_guards": sorted(self.disabled_guards)})
        if guarded:
            if active("capability") and expected.get("tool") == "set_seat_massage" and self.profile != "premium":
                self._trace(trace, "capability", "unsupported", "standard车型未安装按摩功能。")
                return self._result("unsupported", "当前standard车型没有座椅按摩功能，未执行。", expected, trace)
            # A known hazard can be rejected without inventing its missing position.
            if active("safety") and expected.get("tool") in {"set_door", "set_trunk"}:
                safety = self._safety_error(expected)
                if safety:
                    self._trace(trace, "safety", "blocked", safety)
                    return self._result("blocked", safety, expected, trace)
            if active("ambiguity") and expected["kind"] == "clarify":
                self.context = {"pending_plan": expected}
                self._trace(trace, "ambiguity", "clarify", expected["question"])
                return self._result("clarify", expected["question"], expected, trace)
            if expected["kind"] in {"manual", "unsupported", "chat", "state"}:
                proposed = expected
            self._trace(trace, "ambiguity", "ok" if active("ambiguity") else "skipped",
                        "必要信息来自原话或单一有效对话上下文。" if active("ambiguity") else "歧义检查已在离线消融中关闭。")
        else:
            self._trace(trace, "control", "warning", "教学简化对照：跳过新增语义/车型/状态验证；仍经上游VAL。")

        kind = proposed.get("kind")
        if kind == "state":
            self._trace(trace, "state_read", "ok", "状态询问只读取模拟观测，模型候选动作没有执行权限。")
            return self._result("answered", self._state_message(str(text)), proposed, trace)
        if kind == "manual":
            return self._result("answered", "已转交说明书证据检索。", proposed, trace,
                                query=proposed.get("query", text))
        if kind == "unsupported":
            self._trace(trace, "capability", "unsupported", "不存在可调用的注册能力。")
            return self._result("unsupported", proposed.get("question", "本车没有这项能力，未执行。"), proposed, trace)
        if kind == "chat":
            self.context = {}
            return self._result("answered", proposed.get("question") or
                                "我是本地模拟座舱助手，可演示车窗、温度、车门、后备箱、车型能力和手册问答。", proposed, trace)
        if kind == "clarify":
            self.context = {"pending_plan": expected if expected.get("tool") else proposed}
            return self._result("clarify", proposed.get("question", "请补充具体操作。"), proposed, trace)
        if kind != "action":
            return self._result("failed", "未知计划类型，未执行。", proposed, trace)
        tool, args = proposed.get("tool"), proposed.get("args", {})
        if not isinstance(tool, str) or tool not in REGISTRY:
            self._trace(trace, "capability", "unsupported", "工具未注册。")
            return self._result("unsupported", "模型提出了未注册工具，未执行。", proposed, trace)

        errors = sorted(VALIDATORS[tool].iter_errors(args), key=lambda e: str(e.path))
        if errors:
            message = "参数不符合工具JSON Schema：" + errors[0].message
            self._trace(trace, "schema", "blocked", message)
            return self._result("blocked", message, proposed, trace)
        self._trace(trace, "schema", "ok", "参数类型、必填项、范围和额外字段检查通过。")

        if guarded:
            if active("semantic") and expected["kind"] == "action" and (tool != expected.get("tool") or args != expected.get("args")):
                self._trace(trace, "semantic", "blocked", {"expected": expected, "proposed": proposed})
                return self._result("blocked", "工具参数与原话/有效上下文不一致，未执行；请检查规划。", proposed, trace)
            self._trace(trace, "semantic", "ok" if active("semantic") else "skipped",
                        {"slot_sources": expected.get("slot_sources", {})} if active("semantic") else "原话参数一致性检查已在离线消融中关闭。")
            if active("capability") and tool == "set_seat_massage" and self.profile != "premium":
                self._trace(trace, "capability", "unsupported", "standard车型未安装按摩功能。")
                return self._result("unsupported", "当前standard车型没有座椅按摩功能，未执行。", proposed, trace)
            self._trace(trace, "capability", "ok" if active("capability") else "skipped",
                        f"工具存在且符合{self.profile}车型配置。" if active("capability") else "车型能力检查已在离线消融中关闭。")
            if tool not in self.permissions:
                self._trace(trace, "permission", "blocked", "当前会话没有该工具的执行权限。")
                return self._result("blocked", "当前会话没有此操作权限，未执行。", proposed, trace)
            self._trace(trace, "permission", "ok", "会话具备该工具的模拟执行权限。")
            safety = self._safety_error(proposed) if active("safety") else None
            if safety:
                self._trace(trace, "safety", "blocked", safety)
                return self._result("blocked", safety, proposed, trace)
            self._trace(trace, "safety", "ok" if active("safety") else "skipped",
                        "车态新鲜度、车速、档位及硬性规则检查通过。" if active("safety") else "新增安全检查已在离线消融中关闭，上游VAL仍生效。")

        if self._requires_confirmation(tool):
            self.context = {}
            token = secrets.token_urlsafe(24)
            self.pending = {"token": token, "plan": copy.deepcopy(proposed), "text": str(text),
                            "mode": mode, "revision": self.revision, "profile": self.profile,
                            "permissions": sorted(self.permissions), "created_at": time.monotonic(),
                            "disabled_guards": sorted(self.disabled_guards),
                            "digest": self._digest(proposed)}
            message = "请确认模拟操作：" + self._description(proposed) + "。"
            self._trace(trace, "confirmation", "pending", "确认绑定具体计划、车型、权限、状态版本；有效期45秒。")
            return self._result("confirm", message, proposed, trace,
                                pending={"token": token, "description": message, "expires_in": 45,
                                         "revision": self.revision})
        return self._execute(proposed, trace, guarded=guarded)

    def _state_message(self, text):
        state = self.vehicle()
        parts = []
        positions = list(dict.fromkeys(p for word in scan_positions(text) for p in ids_of(word) if p in POSITIONS))
        selected = positions or POSITIONS
        if re.search(r"车窗|窗户", text):
            parts.append("车窗开度：" + "，".join(f"{LABELS[p]} {state['windows'][p]}%" for p in selected))
        if re.search(r"空调|温度", text):
            parts.append(f"空调设定温度 {state['temperature']}℃")
        if re.search(r"车门|门锁", text):
            parts.append("实体车门：" + "，".join(f"{LABELS[p]}{'开启' if state['doors'][p] else '关闭'}" for p in selected))
            if "门锁" in text:
                parts.append("门锁" + ("已解锁" if self.val.state.get("door_lock") == "unlocked" else "已上锁"))
        if re.search(r"后备箱|尾门", text):
            parts.append("后备箱" + ("开启" if state["trunk_open"] else "关闭"))
        if "按摩" in text:
            parts.append("本车型没有按摩功能" if self.profile != "premium" else "按摩" + ("开启" if state["massage"] else "关闭"))
        if not parts or re.search(r"车速|档位|挡位", text):
            parts.append(f"车速 {state['speed']} km/h，档位 {state['gear']}")
        prefix = "模拟车当前观测：" if state["state_age_ms"] <= 10000 else "模拟车观测已过期，以下是此前读数，不能代表当前状态："
        return prefix + "；".join(parts) + "。本次仅查询，未执行车控。"

    @staticmethod
    def _digest(plan):
        return hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def confirm(self, token, approve=True):
        trace = []
        pending = self.pending
        if not isinstance(token, str) or not pending or token in self._used_tokens or not secrets.compare_digest(token, pending["token"]):
            return self._result("blocked", "确认凭据无效、已使用或已被新请求替代，未执行。", {}, trace)
        self.pending = None
        self._used_tokens.add(token)
        plan = pending["plan"]
        if approve is not True:
            return self._result("answered", "已取消，未执行车辆动作。", plan, trace)
        if time.monotonic() - pending["created_at"] > 45:
            return self._result("blocked", "确认已过期，请重新发起操作。", plan, trace)
        if (self.revision != pending["revision"] or self.profile != pending["profile"]
                or sorted(self.permissions) != pending["permissions"] or self._digest(plan) != pending["digest"]
                or sorted(self.disabled_guards) != pending["disabled_guards"]):
            self._trace(trace, "confirmation", "blocked", "确认所绑定的状态或权限已变化。")
            return self._result("blocked", "车辆状态、车型或权限已改变，请重新发起并确认。", plan, trace)
        if pending["mode"] == "guarded" and "safety" not in self.disabled_guards:
            safety = self._safety_error(plan)
            if safety:
                self._trace(trace, "safety", "blocked", safety)
                return self._result("blocked", safety, plan, trace)
        self._trace(trace, "confirmation", "ok", "一次性确认有效，执行前重新检查完毕。")
        return self._execute(plan, trace, confirmed=True, guarded=pending["mode"] == "guarded")

    def _command(self, plan):
        tool, args = plan["tool"], plan["args"]
        data = {"object": OBJECTS[tool]}
        if tool == "set_window":
            data.update(operate="close" if args["percent"] == 0 else "open",
                        positions=[args["position"]], value=args["percent"], unit="percent")
        elif tool == "set_temperature":
            data.update(operate="set", attr="temperature", value=args["celsius"], unit="degree")
        elif tool == "set_door":
            data.update(operate="open" if args["open"] else "close", positions=[args["position"]],
                        interview_physical_door=True)
        elif tool == "set_trunk":
            data.update(operate="open" if args["open"] else "close")
        elif tool == "set_seat_massage":
            data.update(operate="open" if args["enabled"] else "close", mode="massage")
        return {"domain": "vehicle", "intent": tool, "data": data}

    @staticmethod
    def _description(plan):
        tool, a = plan["tool"], plan["args"]
        if tool == "set_window":
            return f"{LABELS[a['position']]}车窗设为{a['percent']}%"
        if tool == "set_temperature":
            return f"空调设为{a['celsius']}℃"
        if tool == "set_door":
            return f"{'打开' if a['open'] else '关闭'}{LABELS[a['position']]}实体车门（模拟）"
        if tool == "set_trunk":
            return ("打开" if a["open"] else "关闭") + "后备箱"
        if tool == "set_seat_massage":
            return ("开启" if a["enabled"] else "关闭") + "座椅按摩"
        return f"将导航目的地设为{a['destination']}"

    def _verify(self, plan, before, after):
        expected = copy.deepcopy(before)
        tool, a = plan["tool"], plan["args"]
        if tool == "set_window":
            expected["windows"][a["position"]] = a["percent"]
        elif tool == "set_temperature":
            expected["temperature"] = a["celsius"]
        elif tool == "set_door":
            expected["doors"][a["position"]] = a["open"]
        elif tool == "set_trunk":
            expected["trunk_open"] = a["open"]
        elif tool == "set_seat_massage":
            expected["massage"] = a["enabled"]
        keys = ("windows", "temperature", "doors", "trunk_open", "massage", "speed", "gear")
        mismatches = [{"field": key, "expected": expected[key], "observed": after[key]}
                      for key in keys if expected[key] != after[key]]
        return not mismatches, mismatches

    def _execute(self, plan, trace, confirmed=False, guarded=True):
        tool, args = plan["tool"], plan["args"]
        if tool == "navigate":
            self.navigation_destination = args["destination"]
            self.revision += 1
            self.context = {"plan": plan}
            self._trace(trace, "execute", "simulated", "仅保存本地模拟目的地，未请求真实地图或执行车辆动作。")
            return self._result("executed", f"模拟导航目的地：{args['destination']}。未获取真实路线。", plan, trace,
                                calls=[{"tool": tool, "args": args, "source": "simulated_navigation"}])
        operation_id = secrets.token_hex(16)
        before = self.vehicle()
        record = self.driver.dispatch(operation_id, self._command(plan), self.val, confirmed=confirmed)
        calls = [{"tool": tool, "args": copy.deepcopy(args), "operation_id": operation_id,
                  "receipt": record["receipt"], "source": "simulated", "executed_via": "VAL.execute",
                  "actual_command": record["actual_command"]}]
        self._trace(trace, "execute", record["receipt"], {"operation_id": operation_id, "via": "VAL.execute"})
        if not record["acknowledgement_received"]:
            # Reconciliation reads the same operation, never sends the side effect again.
            record = self.driver.records[operation_id]
            self._trace(trace, "reconcile", "ok", "ACK丢失：查询本次操作记录并读取模拟状态；没有重发。")
        if not record["ok"]:
            return self._result("blocked", "上游VAL拒绝执行：" + record["message"], plan, trace, calls)
        if guarded and "verification" not in self.disabled_guards:
            ok, mismatches = self._verify(plan, before, self.vehicle())
            if not ok:
                self.context = {}
                self._trace(trace, "verify", "failed", mismatches)
                return self._result("failed", "执行结果不一致：目标未达成或非目标设备改变。已停止自动重试，请检查实际模拟车态。",
                                    plan, trace, calls)
            self._trace(trace, "verify", "ok", "目标状态符合请求，其他受监测设备没有意外变化；证据仅限模拟车。")
        else:
            self._trace(trace, "verify", "skipped", "实验对照仅依据回执，未核对实际目标或非目标状态。")
        self.context = {"plan": copy.deepcopy(plan)}
        return self._result("executed", "模拟车已完成：" + self._description(plan) + "。", plan, trace, calls)
