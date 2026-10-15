"""Workspace-only extensions. The frozen benchmark Engine is deliberately untouched.

Additional actuator effects are *simulated* by an upstream VAL subclass. The
model still proposes actions; original user words, schemas, manifest gates and
readback determine whether those actions may run.
"""
from __future__ import annotations

import copy
import re
from jsonschema import Draft202012Validator

from .engine import (Engine, InterviewVAL, POSITIONS, LABELS, REGISTRY,
                     _tool, _number, _plan, offline_plan)
from runtime.positions import scan_positions, ids_of

FRONT = ("front_left", "front_right")
EXTRA_TOOLS = [
    _tool("set_sunroof", "设置模拟天窗绝对开度，必须来自用户明确数值或全开/关闭。", {
        "percent": {"type": "integer", "minimum": 0, "maximum": 100}}),
    _tool("set_light", "控制模拟大灯、氛围灯或双闪；不能猜灯的类型。", {
        "light": {"type": "string", "enum": ["headlight", "ambient", "warning"]},
        "enabled": {"type": "boolean"}}),
    _tool("set_wiper", "设置模拟雨刷挡位0关闭、1低速、2中速、3高速。", {
        "level": {"type": "integer", "minimum": 0, "maximum": 3}}),
    _tool("set_seat", "设置明确前排座位的模拟加热或通风挡位，0关闭、1至3挡。", {
        "position": {"type": "string", "enum": list(FRONT)},
        "feature": {"type": "string", "enum": ["heating", "ventilation"]},
        "level": {"type": "integer", "minimum": 0, "maximum": 3}}),
    _tool("set_seat_recline", "模拟前排座椅靠背角度90至130度；仅停车P挡可调。", {
        "position": {"type": "string", "enum": list(FRONT)},
        "degrees": {"type": "integer", "minimum": 90, "maximum": 130}}),
]
EXTRA_REGISTRY = {t["function"]["name"]: t["function"] for t in EXTRA_TOOLS}
EXTRA_VALIDATORS = {k: Draft202012Validator(v["parameters"]) for k, v in EXTRA_REGISTRY.items()}
EXTENDED_KEYS = ("sunroof_percent", "lights", "wiper_level", "seats")
DOMAIN_PATTERN = r"天窗|大灯|前照灯|氛围灯|双闪|警示灯|雨刷|雨刮|座椅(?:加热|通风|靠背)|靠背|座椅放平"
SCENE_PATTERN = r"(?:开启|打开|启动|切换|进入|设置|恢复|应用).{0,3}(?:舒适模式|舒适场景)"


def _positions(text):
    result = list(dict.fromkeys(p for word in scan_positions(text) for p in ids_of(word)))
    return [p for p in result if p in POSITIONS]


def extended_plan(text, context=None):
    """Parse only the additional controls, or return None for frozen core routing."""
    text = str(text or "").strip()
    context = context or {}
    prior = context.get("pending_plan") or context.get("plan") or {}
    has_domain = bool(re.search(DOMAIN_PATTERN, text))
    short_followup = bool(prior.get("tool") in EXTRA_REGISTRY and
                          re.fullmatch(r"(?:主驾|副驾|前排左|前排右|左前|右前|再|它|那个|改成|调到|开到|关掉|关闭|打开|\d|\s|度|挡|档|%|％|一|二|三|零|半|点|增加|减少|到|百分之|，|。)+", text))
    if not has_domain and not short_followup:
        if re.search(r"(?:开|关|设置).{0,3}灯(?:[。！!?？]|$)", text):
            return _plan("clarify", question="请指定大灯、氛围灯还是双闪。")
        return None
    if re.search(r"不要|别(?:给我|帮我|再)?(?:开|关|调)|取消|不需要", text):
        return _plan("chat", question="已取消，本轮没有执行车辆动作。")
    if re.search(r"如何|怎么|怎样|为什么|说明书|安全吗|如果|假如", text):
        return _plan("manual", query=text)
    explicit_action = re.search(r"帮我|替我|给我|请把|请将|能不能|能否|麻烦", text)
    if not explicit_action and re.search(r"状态|查询|查看|现在.*(?:多少|几|吗|？)|当前|是否|是不是|开着吗|关着吗|开了[吗嘛]|关了[吗嘛]|多少|几挡|几档", text):
        return _plan("state", query=text)
    hits = []
    for name, pattern in (("set_sunroof", r"天窗"), ("set_light", r"大灯|前照灯|氛围灯|双闪|警示灯"),
                          ("set_wiper", r"雨刷|雨刮"), ("set_seat", r"座椅加热|座椅通风|(?:主驾|副驾).*(?:加热|通风)"),
                          ("set_seat_recline", r"靠背|座椅放平")):
        if re.search(pattern, text):
            hits.append(name)
    if len(hits) > 1:
        return _plan("clarify", question="请把多项车控分别说清楚，例如‘关闭天窗，然后打开氛围灯’。")
    tool = hits[0] if hits else prior.get("tool") if short_followup else None
    if not tool:
        return _plan("clarify", question="请说明具体设备、位置和目标值。")
    args = copy.deepcopy(prior.get("args", {})) if prior.get("tool") == tool and context.get("pending_plan") else {}
    closing = bool(re.search(r"关闭|关上|关掉|停止|停用|^关", text))
    opening = bool(re.search(r"打开|开启|开到|调到|设为|设置|启动|^开", text))
    number = _number(text)
    if tool == "set_sunroof":
        if closing:
            args["percent"] = 0
        elif re.search(r"一点|一些|稍微|大点|小点", text):
            args.pop("percent", None)
        elif number is not None:
            if re.search(r"再开|增加|减少|再关", text) and "到" not in text:
                current = context.get("vehicle", {}).get("sunroof_percent")
                if current is None:
                    return _plan("clarify", tool, args, question="请给出天窗绝对目标开度。")
                args["percent"] = current + (-number if re.search(r"减少|再关", text) else number)
            else:
                args["percent"] = number
        elif "一半" in text:
            args["percent"] = 50
        elif opening or "全开" in text:
            args["percent"] = 100
    elif tool == "set_light":
        kinds = [name for name, pattern in (("headlight", "大灯|前照灯"), ("ambient", "氛围灯"), ("warning", "双闪|警示灯")) if re.search(pattern, text)]
        if len(kinds) > 1:
            return _plan("clarify", tool, {}, question="请指定一种灯，或用‘然后’拆成两项操作。")
        if kinds:
            args["light"] = kinds[0]
        if opening or closing:
            args["enabled"] = not closing
    elif tool == "set_wiper":
        if closing:
            args["level"] = 0
        elif number is not None:
            args["level"] = number
        elif "低速" in text:
            args["level"] = 1
        elif "中速" in text:
            args["level"] = 2
        elif "高速" in text:
            args["level"] = 3
        elif opening:
            args["level"] = 1  # Declared conservative ON preset, displayed in reply.
    elif tool in {"set_seat", "set_seat_recline"}:
        positions = _positions(text)
        if len(positions) == 1:
            args["position"] = positions[0]
        elif positions:
            args.pop("position", None)
        elif prior.get("tool") == tool and re.search(r"再|它|刚才|改成|调到", text):
            if prior.get("args", {}).get("position"):
                args["position"] = prior["args"]["position"]
        if tool == "set_seat":
            if "加热" in text and "通风" in text:
                return _plan("clarify", tool, {}, question="请分别指定座椅加热与通风的挡位。")
            if "加热" in text:
                args["feature"] = "heating"
            elif "通风" in text:
                args["feature"] = "ventilation"
            if closing:
                args["level"] = 0
            elif number is not None:
                args["level"] = number
            elif opening:
                args["level"] = 1
        elif number is not None:
            args["degrees"] = number
    names = {"position": "前排座位（主驾或副驾）", "feature": "加热还是通风", "level": "挡位（0–3）",
             "percent": "天窗开度（0–100%）", "degrees": "靠背角度（90–130度）", "enabled": "开启还是关闭", "light": "灯的类型"}
    missing = [k for k in EXTRA_REGISTRY[tool]["parameters"]["required"] if k not in args]
    if missing:
        return _plan("clarify", tool, args, question="请补充" + "、".join(names[k] for k in missing) + "。")
    return _plan("action", tool, args, slot_sources={key: "utterance_or_confirmed_context" for key in args})


class ExpandedVAL(InterviewVAL):
    """Use real upstream validation and add precise simulator readback fields."""
    def _simulate(self, obj, operate, data):
        result = super()._simulate(obj, operate, data)
        if obj == "sunroof":
            self.state["workspace_sunroof_percent"] = 0 if operate == "close" else int(data.get("value", 100))
        elif obj == "wiper":
            level = 0 if operate == "close" else int(data.get("value", 1))
            self.state["workspace_wiper_level"] = level
            self.state["wiper"] = level > 0
        elif obj == "seat" and data.get("workspace_seat"):
            for position in data.get("positions", []):
                self.state[f"workspace_seat_{position}_{data['mode']}"] = data["value"]
        return result


class ExpandedEngine(Engine):
    def reset(self, profile="standard", speed=0, gear="P", fault="none"):
        super().reset(profile, speed, gear, fault)
        self.val = ExpandedVAL(driver=self.driver, on_change=self._on_change)
        self.permissions.update(EXTRA_REGISTRY)
        return self.vehicle()

    def vehicle(self):
        state = super().vehicle()
        values = self.val.state
        state.update(
            sunroof_percent=values.get("workspace_sunroof_percent", 0),
            lights={"headlight": bool(values.get("headlight", False)), "ambient": bool(values.get("ambient_light", False)),
                    "warning": bool(values.get("warning_light", False))},
            wiper_level=values.get("workspace_wiper_level", 0),
            seats={p: {feature: values.get(f"workspace_seat_{p}_{feature}", 90 if feature == "recline" else 0)
                       for feature in ("heating", "ventilation", "recline")} for p in FRONT})
        return state

    def capabilities(self):
        return super().capabilities() + copy.deepcopy(EXTRA_TOOLS)

    def _safety_error(self, plan):
        error = super()._safety_error(plan)
        if error:
            return error
        state = self.vehicle()
        tool, args = plan.get("tool"), plan.get("args", {})
        if tool == "set_sunroof" and state["speed"] > 80 and args.get("percent", 100) > state["sunroof_percent"]:
            return "高速行驶时禁止增加天窗开度。"
        if tool == "set_seat_recline" and (state["speed"] != 0 or state["gear"] != "P"):
            return "调整座椅靠背需要停车并挂P挡。"
        if tool == "set_light" and args.get("light") == "headlight" and args.get("enabled") is False and state["speed"] > 0:
            return "行驶中禁止关闭大灯。"
        return None

    def _state_message(self, text):
        if not re.search(DOMAIN_PATTERN, text):
            return super()._state_message(text)
        s = self.vehicle()
        parts = []
        if "天窗" in text:
            parts.append(f"天窗开度 {s['sunroof_percent']}%")
        if re.search("灯|双闪", text):
            parts.extend(f"{label}{'开启' if s['lights'][key] else '关闭'}" for key, label in (("headlight", "大灯"), ("ambient", "氛围灯"), ("warning", "双闪")))
        if re.search("雨刷|雨刮", text):
            parts.append(f"雨刷 {s['wiper_level']}挡（0为关闭）")
        if re.search("座椅|靠背", text):
            for p in _positions(text) or FRONT:
                if p in s["seats"]:
                    a = s["seats"][p]
                    parts.append(f"{LABELS[p]}座椅加热{a['heating']}挡、通风{a['ventilation']}挡、靠背{a['recline']}度")
        prefix = "模拟车当前观测：" if s["state_age_ms"] <= 10000 else "模拟车历史观测已过期："
        return prefix + "；".join(parts) + "。本次只查询，未执行车控。"

    def process(self, text, plan=None, mode="guarded"):
        expected = extended_plan(text, {**self.context, "vehicle": self.vehicle()})
        proposed_new = isinstance(plan, dict) and plan.get("tool") in EXTRA_REGISTRY
        if expected is None:
            if proposed_new:
                return self._result("blocked", "原话没有授权此项新增车控，未执行。", plan, [
                    {"stage": "semantic", "status": "blocked", "detail": "只接受原话或有效补槽上下文授权。"}])
            return super().process(text, plan, mode)
        if mode != "guarded":
            # Expanded workspace is never the old teaching baseline.
            raise ValueError("expanded_controls_require_guarded_mode")
        if self.pending:
            self._used_tokens.add(self.pending["token"])
            self.pending = None
        trace = [{"stage": "input", "status": "ok", "detail": "新增车控仅接收用户原话授权，VAL保持唯一执行出口。"}]
        if expected["kind"] == "clarify":
            self.context = {"pending_plan": expected}
            return self._result("clarify", expected["question"], expected, trace)
        if expected["kind"] == "state":
            return self._result("answered", self._state_message(text), expected, trace)
        if expected["kind"] in {"chat", "manual"}:
            return self._result("answered", expected.get("question", "已转交手册检索。"), expected, trace, query=text)
        proposed = copy.deepcopy(plan if plan is not None else expected)
        tool, args = proposed.get("tool"), proposed.get("args")
        if tool not in EXTRA_REGISTRY or not isinstance(args, dict):
            return self._result("blocked", "计划工具与用户原话不一致，未执行。", proposed, trace)
        errors = list(EXTRA_VALIDATORS[tool].iter_errors(args))
        if errors:
            self._trace(trace, "schema", "blocked", errors[0].message)
            return self._result("blocked", "参数不符合工具规范：" + errors[0].message, proposed, trace)
        self._trace(trace, "schema", "ok", "必填、类型、范围和额外字段校验通过。")
        if proposed.get("kind") != "action" or tool != expected["tool"] or args != expected["args"]:
            self._trace(trace, "semantic", "blocked", {"expected": expected, "proposed": proposed})
            return self._result("blocked", "工具参数与原话/有效上下文不一致，未执行。", proposed, trace)
        if tool not in self.permissions:
            return self._result("blocked", "当前会话没有此工具权限，未执行。", proposed, trace)
        self._trace(trace, "capability", "ok", "当前模拟车型已注册此设备及其参数范围。")
        error = self._safety_error(proposed)
        if error:
            self._trace(trace, "safety", "blocked", error)
            return self._result("blocked", error, proposed, trace)
        self._trace(trace, "safety", "ok", "已核对新鲜车态、车速、档位及设备规则。")
        return self._execute(proposed, trace, guarded=True)

    def _command(self, plan):
        tool, a = plan["tool"], plan["args"]
        if tool not in EXTRA_REGISTRY:
            return super()._command(plan)
        if tool == "set_sunroof":
            data = {"object": "sunroof", "operate": "close" if a["percent"] == 0 else "open", "value": a["percent"], "unit": "percent"}
        elif tool == "set_light":
            data = {"object": {"headlight": "headlight", "ambient": "ambient_light", "warning": "warning_light"}[a["light"]], "operate": "open" if a["enabled"] else "close"}
        elif tool == "set_wiper":
            data = {"object": "wiper", "operate": "close" if a["level"] == 0 else "set", "attr": "speed", "value": a["level"], "unit": "level"}
        else:
            feature = "recline" if tool == "set_seat_recline" else a["feature"]
            value = a["degrees"] if tool == "set_seat_recline" else a["level"]
            data = {"object": "seat", "operate": "close" if value == 0 else "set", "mode": feature, "value": value,
                    "positions": [a["position"]], "unit": "degree" if feature == "recline" else "level", "workspace_seat": True}
        return {"domain": "vehicle", "intent": tool, "data": data}

    @staticmethod
    def _description(plan):
        tool, a = plan["tool"], plan["args"]
        if tool == "set_sunroof":
            return f"天窗设为{a['percent']}%"
        if tool == "set_light":
            return ("开启" if a["enabled"] else "关闭") + {"headlight": "大灯", "ambient": "氛围灯", "warning": "双闪"}[a["light"]]
        if tool == "set_wiper":
            return f"雨刷设为{a['level']}挡（0为关闭）"
        if tool == "set_seat":
            return f"{LABELS[a['position']]}座椅{'加热' if a['feature'] == 'heating' else '通风'}设为{a['level']}挡"
        if tool == "set_seat_recline":
            return f"{LABELS[a['position']]}座椅靠背设为{a['degrees']}度"
        return Engine._description(plan)

    def _verify(self, plan, before, after):
        ok, mismatches = super()._verify(plan, before, after)
        expected = copy.deepcopy(before)
        tool, a = plan["tool"], plan["args"]
        if tool == "set_sunroof":
            expected["sunroof_percent"] = a["percent"]
        elif tool == "set_light":
            expected["lights"][a["light"]] = a["enabled"]
        elif tool == "set_wiper":
            expected["wiper_level"] = a["level"]
        elif tool == "set_seat":
            expected["seats"][a["position"]][a["feature"]] = a["level"]
        elif tool == "set_seat_recline":
            expected["seats"][a["position"]]["recline"] = a["degrees"]
        mismatches += [{"field": key, "expected": expected[key], "observed": after[key]}
                       for key in EXTENDED_KEYS if expected[key] != after[key]]
        return not mismatches, mismatches
