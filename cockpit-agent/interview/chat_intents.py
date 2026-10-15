"""Conservative shortcuts for explicit single-service requests.

Extract only literal user slots. Execution still uses the runtime's registered
tools, schema/intent checks, real providers and address disambiguation.
Unmatched or compound language belongs to the model planner.
"""
import re


POLITE = r"(?:(?:请你|请|麻烦你|麻烦|帮我|给我)\s*)*"
NON_DIRECT = r"不要|别|不用|不想|不需要|不必|暂不|还没|无需|取消|如果|假如|假设|等.+再|能否支持|支持吗|怎么实现|如何实现|怎么使用|如何使用|教程|例子|举例|[‘’“”\"「」]"
COMPOUND = r"然后|并且|同时|以及|顺便|接着|再把|并把|再调|再开|再关|途经|经过|沿途|避开|不走|高速|收费|天气|新闻|提醒|记住|搜索|车窗|空调|温度|车门|天窗|大灯|雨刷|座椅|后备箱|尾门|双闪|按摩"
TRAVEL_QUESTION = r"(?:怎么|如何|怎样)(?:开车|驾车)?(?:去(?!除)|到|前往|去往)|(?:怎么|如何|怎样)(?:走|开车走)|(?:我想|我要)(?:去|到|前往)|导航(?:到|去)"


def explicit_route(text):
    """Return both endpoints only for an unqualified single driving request."""
    text = text.strip().rstrip("。！!？?").strip()
    if re.search(NON_DIRECT + "|" + COMPOUND + r"|公交|地铁|步行|骑行", text):
        return None
    place = r"([^，,；;。！？?!]{1,120}?)"
    driving = r"(?:驾车|开车|驾驶)?"
    tail = rf"(?:\s*[，,]?\s*{POLITE}(?:规划|安排)(?:一下|一条)?{driving}路线|(?:的)?{driving}路线)?"
    patterns = [
        rf"{POLITE}(?:我想|我要)?从{place}(?:出发)?\s*[，,]?\s*(?:到|去|前往){place}{tail}",
        rf"{POLITE}(?:规划|安排)(?:一下|一条)?从{place}(?:出发)?(?:到|去){place}(?:的)?{driving}路线",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, text)
        if not match:
            continue
        origin, destination = (v.strip() for v in match.groups())
        # Do not turn another action or unresolved reference into a place name.
        if any(re.search(r"规划|路线|导航|帮我|给我|出发|[，,；;]|打开|关闭|查询|多久|多远|多少|怎么|如何|能否|可以吗|什么时候", v)
               or v in {"这里", "那里", "这儿", "那儿", "家", "公司", "当前位置"}
               for v in (origin, destination)):
            return None
        return {"origin": origin, "destination": destination}
    return None


def destination_route(text):
    """Extract a literal destination from a single travel question, across cities."""
    text = text.strip().rstrip("。！!？?").strip()
    if re.search(NON_DIRECT + "|" + COMPOUND + r"|公交|地铁|步行|骑行|说明书|手册|去除|[，,；;]", text):
        return None
    query = rf"{POLITE}(?:(?:查询|查|看看|问|知道|了解)(?:一下)?)?"
    if re.fullmatch(rf"{query}(?:怎么|如何|怎样)(?:开车|驾车)?(?:去|到|前往)", text):
        return {}
    place = r"(?P<place>[^，,；;。！？?!]{1,120}?)"
    patterns = [
        rf"{query}(?:怎么|如何|怎样)(?:开车|驾车)?(?:到达|前往|去往|去|到){place}",
        rf"{query}(?:去|到|前往)?{place}(?:该|要)?(?:怎么|如何|怎样)(?:走|去|开车去|驾车去|开车走)",
        rf"{POLITE}(?:我想|我要)(?:去|到|前往){place}",
        rf"{query}(?:去|到|前往){place}的(?:驾车|开车)?路线",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, text)
        if not match:
            continue
        destination = match.group("place").strip()
        if (re.search(r"从|规划|路线|导航|出发|查询|知道|帮我|给我|如何|怎么|怎样|打开|关闭|设置|开车|驾车|多久|多远|多少|哪里|哪儿|什么|有没有|[吗呢]$", destination)
                or destination in {"这里", "那里", "这儿", "那儿", "家", "公司", "当前位置"}):
            return None
        return {"destination": destination}
    return None


def route_constraints(text):
    """Also check explicit endpoints in a route preceding another task."""
    direct = explicit_route(text) or destination_route(text)
    if direct:
        return direct
    first = re.split(r"然后|并且|同时|以及|顺便|接着|并把|再把", text, maxsplit=1)[0].strip(" ，,；;")
    return (explicit_route(first) or destination_route(first)) if first != text else None


def news_request(text):
    text = text.strip().rstrip("。！!？?").strip()
    if re.search(NON_DIRECT + r"|然后|并且|同时|以及|顺便|[，,；;]|天气|导航|提醒|记住", text):
        return None
    pattern = (rf"{POLITE}(?:(?:查(?:一下)?|查询|看看|看一下|看|播报)(?:一下)?)?"
               r"(?P<period>今天|今日|最新|最近)?(?:有(?:什么|哪些)?|的)?"
               r"(?P<topic>[^，,；;。！？?!]{0,20}?)?(?:的)?新闻(?:有(?:什么|哪些)|吗)?")
    match = re.fullmatch(pattern, text)
    if not match:
        return None
    topic = (match.group("topic") or "").strip().removesuffix("的")
    if topic and re.search(r"查|看|什么|哪些|不要|怎么|如何|打开|关闭|帮我|给我|规划|路线", topic):
        return None
    args = {"topic": topic} if topic else {}
    if match.group("period") in {"今天", "今日"}:
        args["period"] = "today"
    return args
