#!/usr/bin/env python3
"""Generate a nine-page, offline interview deck from actual saved results.

Only the Python standard library is required. This script does not make network
requests or execute evaluations. Run it again after results/summary.json changes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from html import escape
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATEGORIES = [
    ("ambiguity", "歧义处理"), ("tool_calling", "工具调用"),
    ("capability", "能力边界"), ("safety", "安全规则"), ("rag", "手册证据"),
]


def esc(value):
    return escape(str(value), quote=True)


def read_json(path):
    if not path.exists():
        return {}
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"无法读取结果文件 {path.name}: {type(exc).__name__}") from None
    if not isinstance(result, dict):
        raise SystemExit(f"结果文件 {path.name} 必须是 JSON 对象")
    return result


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def pct(value):
    n = number(value)
    return "未记录" if n is None else f"{100*n:.1f}%"


def integer(value):
    n = number(value)
    return "未记录" if n is None else f"{int(n):,}"


def latency(value):
    n = number(value)
    if n is None:
        return "未记录"
    return f"{n/1000:.2f} s" if n >= 1000 else f"{n:.1f} ms"


def groups(data, provider=None):
    return [g for g in data.get("groups", []) if isinstance(g, dict)
            and (provider is None or g.get("provider") == provider)]


def by_mode(data, provider):
    return {g.get("mode"): g for g in groups(data, provider)}


def image(filename, caption):
    path = ROOT / "results" / "screenshots" / filename
    if not path.is_file():
        return '<div class="screenshot absent">运行截图尚未生成</div>'
    return (f'<figure class="screenshot"><img src="../results/screenshots/{esc(filename)}" '
            f'alt="{esc(caption)}"><figcaption>{esc(caption)}</figcaption></figure>')


def heading(kicker, title, subtitle=""):
    return (f'<header><div class="kicker">{esc(kicker)}</div><h1>{esc(title)}</h1>'
            + (f'<p class="subtitle">{esc(subtitle)}</p>' if subtitle else "") + '</header>')


def footer(index, source="模拟车辆 · 本地面试项目"):
    return (f'<footer><span>经纬 · 可信座舱 <i>/</i> {esc(source)}</span>'
            f'<span class="page">{index:02d}<small> / 09</small></span></footer>')


def slide(index, body, cls=""):
    return f'<section class="slide {esc(cls)}" data-page="{index}" aria-label="第 {index} 页">{body}{footer(index)}</section>'


def table(data, provider="kimi"):
    rows = []
    for g in groups(data, provider):
        name = {"baseline": "方案前（简化对照）", "guarded": "方案后（可信执行）"}.get(g.get("mode"), g.get("name", "未命名组"))
        rows.append('<tr>' + ''.join([
            f'<td><strong>{esc(name)}</strong><small>{esc(g.get("model", "模型未记录"))}</small></td>',
            f'<td>{esc(integer(g.get("passed")))}/{esc(integer(g.get("total")))}</td>',
            f'<td class="number">{esc(pct(g.get("pass_rate")))}</td>',
            f'<td>{esc(pct(g.get("consistent_rate")))}</td>',
            f'<td>{esc(latency(g.get("p95_latency_ms")))}</td>',
        ]) + '</tr>')
    if not rows:
        return '<div class="empty">尚无已完成结果；本页不填入预测数字。</div>'
    return ('<table class="result-table"><thead><tr><th>实验组 / 实际模型</th><th>通过 / 运行</th>'
            '<th>单次通过率</th><th>全部重复均通过</th><th>P95 延迟</th></tr></thead>'
            '<tbody>' + ''.join(rows) + '</tbody></table>')


def category_bars(data, provider):
    paired = by_mode(data, provider)
    if not paired:
        return '<div class="empty">此组结果尚未生成。</div>'
    items = []
    for key, label in CATEGORIES:
        bits = []
        for mode, short, css in [('baseline', '方案前', 'base'), ('guarded', '方案后', 'guard')]:
            cat = paired.get(mode, {}).get("categories", {}).get(key, {})
            n = number(cat.get("pass_rate"))
            width = max(0, min(100, n*100)) if n is not None else 0
            bits.append(f'<div class="bar-row"><span>{short}</span><div class="bar-track"><i class="{css}" '
                        f'style="width:{width:.3f}%"></i></div><b>{esc(pct(cat.get("pass_rate")))}</b></div>')
        before = paired.get("baseline", {}).get("categories", {}).get(key, {})
        after = paired.get("guarded", {}).get("categories", {}).get(key, {})
        b = before.get("passed", 0) / before["total"] if before.get("total") else None
        g = after.get("passed", 0) / after["total"] if after.get("total") else None
        change = f"{100*(g-b):+.2f} 个百分点" if b is not None and g is not None else "尚未完成"
        items.append(f'<div class="bar-item"><h3>{esc(label)}</h3>{"".join(bits)}<small class="category-change">{change}</small></div>')
    return '<div class="category-bars">' + ''.join(items) + '</div>'


def challenge_note(data):
    pair = by_mode(data, "kimi")
    if not pair:
        return '<p>独立挑战尚无已完成数据；运行后重新生成本汇报。</p>'
    rows = []
    for key, label in CATEGORIES:
        b = number(pair.get("baseline", {}).get("categories", {}).get(key, {}).get("pass_rate"))
        g = number(pair.get("guarded", {}).get("categories", {}).get(key, {}).get("pass_rate"))
        if b is None or g is None:
            continue
        diff = 100*(g-b)
        css = "negative" if diff < -.001 else ("positive" if diff > .001 else "neutral")
        note = "出现退步，保留失败" if diff < -.001 else ("本次观察到改善" if diff > .001 else "本次没有改善")
        rows.append(f'<tr><td>{esc(label)}</td><td>{esc(pct(b))} → {esc(pct(g))}</td>'
                    f'<td class="{css}">{diff:+.1f} pp</td><td>{note}</td></tr>')
    return ('<table class="compact"><thead><tr><th>类别</th><th>对照 → 可信</th><th>变化</th><th>解释</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')


def make_deck(summary, challenge):
    model_groups = groups(summary, "kimi")
    chart_provider = "kimi"
    chart_title = "各类准确率（完整用例通过率）"
    date = summary.get("generated_at", "尚未生成")
    total_cases = integer(summary.get("cases"))
    repeats = integer(summary.get("repeats"))
    kimi_note = "本页只展示真实 Kimi 方案前/后。" if model_groups else "真实 Kimi 主实验尚未完成，不用离线或历史分数代替。"
    pair = by_mode(summary, "kimi")
    before, after = pair.get("baseline", {}), pair.get("guarded", {})
    if before.get("total") and after.get("total"):
        overall_delta = f"整体准确率变化：{100*(after['passed']/after['total'] - before['passed']/before['total']):+.2f} 个百分点"
    else:
        overall_delta = "尚无完整方案前/后结果"
    source_changed = summary.get("source_changed_during_run") is True
    version_note = '<strong class="negative">注意：运行期间源码发生变化，结果需重新核对。</strong>' if source_changed else '结果按运行器记录的源码与语料哈希追溯。'
    slides = []
    slides.append(slide(1,
        heading("INTERVIEW PROJECT / 01", "经纬 · 可信座舱", "把一次“听懂了”，变成一次有证据的执行。") +
        '<div class="hero-grid"><div><div class="tag">基于开源 cockpit-agent · 仅模拟车辆</div>'
        '<h2 class="hero-title">模型提出计划<br>系统决定行动</h2><p class="lead">围绕五类车载 Agent 可靠性问题，完成实现、故障实验与证据展示。</p>'
        '<div class="hero-numbers"><div><b>5</b><span>可靠性问题</span></div><div><b>6</b><span>基础评测工具</span></div>'
        f'<div><b>{total_cases}</b><span>开发回归用例</span></div></div><p class="dim">不接实车总线，不把底座能力全部算作个人原创。</p></div>' +
        image('01_studio_desktop.png', '本地新 HMI：对话、车辆与执行证据') + '</div>', 'cover'))
    slides.append(slide(2,
        heading("SYSTEM / 02", "把执行权留在确定性边界内", "同一服务函数连接网页与评测；车辆控制统一经过 VAL。") +
        '<div class="flow"><div><b>01</b><strong>用户原话</strong><span>上下文 / 模拟车态</span></div><i>→</i>'
        '<div><b>02</b><strong>Kimi 计划</strong><span>工具 + 参数</span></div><i>→</i>'
        '<div class="accent"><b>03</b><strong>运行时检查</strong><span>完整性 · 能力 · 安全</span></div><i>→</i>'
        '<div><b>04</b><strong>VAL 执行</strong><span>原底层校验保留</span></div><i>→</i>'
        '<div><b>05</b><strong>结果对账</strong><span>目标 + 非目标状态</span></div></div>'
        '<div class="two-columns"><article class="card"><div class="eyebrow">复用的底座</div><h2>成熟架构，保留边界</h2>'
        '<p>原 VAL / 模拟驱动、React + TypeScript 构建体系、原系统源码与许可。</p>'
        '<p class="muted">扩展版另接业务服务、持久偏好与多模态；未启动原 Go / gRPC / NATS 全部分布式服务。</p></article>'
        '<article class="card"><div class="eyebrow">本次的增量</div><h2>可检查的本地运行时</h2>'
        '<p>FastAPI + Kimi 接入、四窗与实体门模拟、五类守卫、故障注入、配对评估和新 UI。</p>'
        '<code>service.turn → Engine.process → VAL.execute</code></article></div>'
        '<div class="ribbon">知识分支：原始问题 → 手册检索 → 条件与警告扩展 → 带来源事实回答</div>'))
    slides.append(slide(3,
        heading("AMBIGUITY + TOOL CALLING / 03", "先把目标说清，再检查是否做对", "机制示例：不把合法 JSON 等同于正确执行。") +
        '<div class="two-columns"><article class="card"><div class="eyebrow">01 / 信息不完整</div><h2>“帮我打开一点”</h2>'
        '<div class="chips"><span>对象？</span><span>位置？</span><span>幅度？</span></div>'
        '<div class="outcome amber">澄清 · 车辆状态保持不变</div><p>原话和单一有效上下文提供参数；当前车态不能代替用户意图。</p>'
        '<div class="small-flow">补充“副驾车窗开50%” <b>↓</b><code>set_window(front_right, 50)</code></div></article>'
        '<article class="card"><div class="eyebrow">02 / 三层验证</div><h2>格式、目标、效果</h2>'
        '<ol class="steps"><li><b>Schema</b><span>参数类型、位置枚举、0–100% 开度</span></li>'
        '<li><b>语义对齐</b><span>副驾是 front_right；rear_right 合法但不对题</span></li>'
        '<li><b>执行后核对</b><span>目标窗达到50%，其它三窗没有改变</span></li></ol>'
        '<div class="outcome red">错目标故障 → 检测失败并保留实际状态</div></article></div>'
        '<div class="bottom-grid"><div><b>模拟器增量</b><span>一个 window 标量 → 四窗独立状态</span></div>'
        '<div><b>丢 ACK</b><span>查询同一操作记录 → 回读 → 不盲重发</span></div></div>'))
    slides.append(slide(4,
        heading("CAPABILITY + SAFETY / 04", "能不能做，由真实能力与状态决定", "同一句需求，在不同配置与车态下应得到不同结果。") +
        '<div class="two-columns"><article class="card"><div class="eyebrow">03 / 能力边界</div><h2>“打开座椅按摩”</h2>'
        '<div class="comparison"><div><span>STANDARD</span><strong>无按摩能力</strong><b class="amber-text">不支持 · 无写入</b></div>'
        '<div><span>PREMIUM</span><strong>存在按摩能力</strong><b class="teal-text">检查通过后执行</b></div></div>'
        '<p>规划器目录先过滤，派发前再检查。模型说“已完成”不能成为成功证据。</p></article>'
        '<article class="card"><div class="eyebrow">04 / 安全规则</div><h2>“打开副驾车门”</h2>'
        '<div class="policy-row"><b>100 km/h · D</b><span class="outcome red">硬性拦截</span></div>'
        '<div class="policy-row"><b>0 km/h · P</b><span class="outcome amber">等待确认</span></div>'
        '<div class="policy-row"><b>车态过期 / 旧确认</b><span class="outcome red">拒绝执行</span></div>'
        '<p>确认绑定计划、配置、权限和状态版本；45 秒期限、一次消费、执行前复核。</p></article></div>'
        '<div class="ribbon navy">用户“我确认了”不能覆盖行驶安全硬规则。以上为本地模拟政策，不是量产认证。</div>'))
    slides.append(slide(5,
        heading("GROUNDED RAG / 05", "警告要召回，适用条件也不能丢", "示例资料：Volvo EC40 2026 · 英国版；不能套用到任意车型。") +
        '<div class="rag-layout"><div><table class="condition-table"><thead><tr><th>儿童座椅条件</th><th>该手册的气囊要求</th></tr></thead><tbody>'
        '<tr><td>前排副驾 · 后向</td><td><b class="amber-text">停用 / 关闭</b>副驾气囊</td></tr>'
        '<tr><td>前排副驾 · 前向</td><td><b class="teal-text">启用 / 开启</b>副驾气囊</td></tr>'
        '<tr><td>后排安装</td><td>不直接套用前排关闭规则</td></tr>'
        '<tr><td>车型 / 位置 / 朝向不足</td><td>条件说明 + 澄清，不给统一结论</td></tr></tbody></table>'
        '<div class="retrieval"><span>BM25 + 字符 TF-IDF</span><b>↓</b><span>RRF + 主题重排</span><b>↓</b>'
        '<span class="emphasized">主题召回 → 条件警告扩展</span><b>↓</b><span>来源事实渲染 / 无证据弃答</span></div></div>'
        '<aside><div class="metric-card"><b>11</b><span>有来源的演示事实块</span></div><p>不是 dense embedding；不是神经 reranker；不是任意自由答案的事实校验器。</p>'
        '<div class="note">当前覆盖收益主要来自条件事实扩展和受控渲染，不能直接归因于混合检索。</div>'
        '<code>rag.py + data/manual.json</code></aside></div>'))
    slides.append(slide(6,
        heading("PAIRED EVALUATION / 06", "方案前后，准确率怎样变化", f'{total_cases} 个开发回归案例 × {repeats} 次；数据读取 results/summary.json。') +
        f'<p class="data-stamp">{esc(kimi_note)} <span>记录时间：{esc(date)}</span></p>' + table(summary, 'kimi') +
        f'<div class="chart-heading"><h2>{esc(chart_title)}</h2><span><i class="legend base"></i>方案前 <i class="legend guard"></i>方案后</span></div>' +
        category_bars(summary, chart_provider) + f'<div class="ribbon">{esc(overall_delta)}</div>' +
        '<div class="fineprint">简化对照保留原 VAL，不代表完整上游。两组回放同一候选；多轮使用可信分支的历史。'
        '方案前关闭部分新增约束，方案后启用约束；不是模型微调前后。分数不代表实车安全保证。<br>' +
        version_note + '</div>', 'results-slide'))
    challenge_cases = integer(challenge.get("cases"))
    challenge_repeats = integer(challenge.get("repeats"))
    slides.append(slide(7,
        heading("HISTORICAL EVIDENCE / 07", "历史挑战：局限仍然保留", f'旧120例阶段的补充：{challenge_cases}例 × {challenge_repeats}次；不计入本轮{total_cases}例成绩。') +
        table(challenge, 'kimi') +
        '<div class="challenge-grid"><div>' + challenge_note(challenge) + '</div>'
        '<aside class="card compact-card"><h2>证据边界</h2><ul class="plain-list">'
        f'<li>本轮{total_cases}条主集开发可见，不是盲测。</li>'
        '<li>本页挑战由同一团队编写，是历史补充。</li>'
        '<li>规则会误澄清；不能只报拒绝收益。</li>'
        '<li>内存操作记录不保证跨重启恰好一次。</li>'
        '<li>RAG 评分是词法近似，仍需人工检查条件。</li>'
        '<li>未接实车；未启动原完整多服务系统。</li></ul></aside></div>'
        '<div class="ribbon">没有改善就报告没有改善；发现退步就保留反例，下一轮使用新验证集评估修复。</div>', 'results-slide'))
    slides.append(slide(8,
        heading("CONTRIBUTION + DEMO / 08", "可以被追问的贡献，才是展示重点", "来源明确，机制可解释，结果能复现。") +
        '<div class="two-columns"><article class="card"><div class="eyebrow">复用与理解</div><h2>保留开源底座</h2>'
        '<p>车辆抽象层、基础模拟驱动、React 工程结构、原多 Agent 架构与源码。</p>'
        '<p class="muted">保留许可和来源；不把全部底座能力表述成自己从零开发。</p></article>'
        '<article class="card"><div class="eyebrow">本次实现与验证</div><h2>把五个问题做成闭环</h2>'
        '<p>按座位状态、五类运行时约束、故障对账、条件手册证据、新 UI、用例与评估产物。</p>'
        '<p class="muted">已有机制可以独立重实现；不声称首创，也不预设一定优于原项目。</p></article></div>'
        '<h2 class="demo-title">现场演示顺序</h2><div class="demo-sequence">'
        '<div><b>1</b><strong>打开一点</strong><span>先澄清</span></div><div><b>2</b><strong>副驾50%</strong><span>目标与结果一致</span></div>'
        '<div><b>3</b><strong>标准档按摩</strong><span>能力缺失</span></div><div><b>4</b><strong>高速开门</strong><span>硬性拦截</span></div>'
        '<div><b>5</b><strong>儿童座椅</strong><span>保留条件与引用</span></div></div>'
        '<div class="closing"><code>.venv/bin/python start.py</code><span>本地：127.0.0.1:8787 · 结果：results/summary.json</span></div>'))
    slides.append(slide(9,
        heading("EXPANDED WORKSPACE / 09", "把可靠性放进完整的出行任务", "新增功能独立验收；前面的 250 例准确率只属于基础可信机制。") +
        '<div class="two-columns"><article class="card"><div class="eyebrow">一句话，多项任务</div><h2>查天气 → 规划路线 → 调空调</h2>'
        '<p>真实地图、POI、天气、新闻与搜索；根据工具结果继续规划，并保留“第二家”和途经点上下文。</p>'
        '<p>明确车控走确定性快路径；复杂任务由 Kimi 提计划，最多 4 轮、8 个工具步骤。</p>'
        '<p class="muted">公开路线不含实时交通与充电空闲；数据源失败时明确说明。</p></article>'
        '<article class="card"><div class="eyebrow">不止文本按钮</div><h2>记忆、手册、语音与视觉</h2>'
        '<p>SQLite 偏好与提醒；3 份完整官方 PDF，按车型、地区检索并跳转页码。</p>'
        '<p>浏览器语音自动发送、播报与打断；Gemma 单帧视觉只读分析，图片不执行车控。</p>'
        '<p class="muted">新增天窗、灯光、雨刷、座椅和舒适场景，仍经过 VAL 模拟执行与验证。</p></article></div>'
        '<div class="ribbon">现场链路：找地点 → 选第二家 → 加途经点 → 保存偏好 → 新会话开启舒适模式</div>'
        '<p class="fineprint">详情：docs/06_扩展功能与演示路线.md · 原始验收：results/expansion_acceptance.json。'
        '语音依赖支持的浏览器与 localhost/HTTPS；未验证实体麦克风、摄像头和实车设备。Android 与完整端云集群不在本次范围。</p>'))
    return '\n'.join(slides)


STYLE = r'''
:root{--navy:#142742;--ink:#1c304c;--slate:#66758b;--paper:#f3f6f9;--line:#dae2ec;--teal:#187f87;--amber:#a26c17;--red:#a74a49;--base:#8c9db2;--guard:#187f87}
*{box-sizing:border-box}html,body{margin:0}body{font-family:"Noto Sans CJK SC","Microsoft YaHei","PingFang SC",system-ui,sans-serif;background:#dce3ec;color:var(--ink);font-size:16px;line-height:1.5}button{font:inherit}code{font-family:ui-monospace,"Cascadia Code",monospace;font-size:.83em;overflow-wrap:anywhere}.deck{padding:34px 0 90px}.slide{position:relative;display:flex;flex-direction:column;width:1122px;height:794px;margin:0 auto 28px;background:var(--paper);padding:42px 52px 54px;overflow:hidden;box-shadow:0 10px 45px #152b4520;border-top:7px solid var(--navy)}header{margin-bottom:25px}.kicker{font-size:12px;letter-spacing:2px;font-weight:700;color:var(--teal);margin-bottom:10px}h1{font-size:36px;line-height:1.2;letter-spacing:-.7px;margin:0 0 12px;font-weight:760}h2{font-size:23px;line-height:1.35;margin:0 0 14px}h3{font-size:14px;margin:0 0 8px}p{margin:12px 0;font-size:17px}.subtitle{margin:0;color:var(--slate);font-size:16px}footer{position:absolute;left:52px;right:52px;bottom:20px;border-top:1px solid var(--line);padding-top:10px;display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--slate)}footer i{font-style:normal;color:#bac5d3;margin:0 8px}.page{font-size:18px;font-weight:700;color:var(--ink)}.page small{font-size:11px;font-weight:400;color:var(--slate)}.two-columns{display:grid;grid-template-columns:1fr 1fr;gap:22px}.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:25px 28px}.eyebrow{font-size:12px;letter-spacing:1px;font-weight:700;color:var(--teal);margin-bottom:12px}.muted,.dim{color:var(--slate)}.muted{font-size:15px}.tag{font-size:12px;border:1px solid #42617f;display:inline-block;padding:6px 11px;border-radius:20px;color:#c4d9ea}.cover{background:var(--navy);color:white;border-top-color:#38b8b2}.cover .kicker{color:#80d6d2}.cover .subtitle,.cover .dim{color:#b0c3d7}.cover footer{border-color:#39506b;color:#adc1d6}.cover footer .page{color:white}.hero-grid{display:grid;grid-template-columns:40% 60%;gap:28px;align-items:center;margin-top:14px}.hero-title{font-size:40px;line-height:1.38;margin:27px 0 20px;letter-spacing:-.4px}.lead{font-size:18px;line-height:1.8;color:#d6e0ee}.hero-numbers{display:flex;gap:34px;margin:27px 0}.hero-numbers b{display:block;font-size:38px;line-height:1.3;font-weight:650;color:#80d6d2}.hero-numbers span{font-size:12px;color:#b6c9df}.dim{font-size:12px}.screenshot{margin:0;border-radius:14px;overflow:hidden;background:#eef3f7;border:1px solid #617893;box-shadow:0 18px 50px #05142645}.screenshot img{width:100%;display:block}.screenshot figcaption{font-size:11px;padding:10px 15px;color:var(--ink);background:#e5edf5}.absent{height:300px;display:grid;place-items:center;color:var(--slate)}.flow{display:flex;align-items:stretch;gap:8px;margin:10px 0 27px}.flow>div{flex:1;min-width:0;padding:18px 12px;background:white;border:1px solid var(--line);border-radius:12px}.flow>i{font-style:normal;align-self:center;color:#8e9eaf;font-size:22px}.flow b,.flow strong,.flow span{display:block}.flow b{font-size:11px;color:var(--teal);margin-bottom:8px}.flow strong{font-size:18px;margin-bottom:8px}.flow span{font-size:12px;color:var(--slate)}.flow .accent{background:var(--navy);border-color:var(--navy);color:white}.flow .accent span{color:#b7c8dc}.flow .accent b{color:#75d8d3}.ribbon{padding:16px 22px;margin-top:24px;background:#e2edf0;border-radius:10px;color:#31556b;font-size:16px}.ribbon.navy{background:var(--navy);color:#dfebf5}.chips{display:flex;gap:10px;margin:20px 0}.chips span{padding:9px 18px;background:#eef2f7;border-radius:8px;color:var(--slate)}.outcome{display:block;padding:11px 15px;border-radius:7px;font-weight:650;font-size:15px}.outcome.amber{background:#fff3dc;color:var(--amber)}.outcome.red{background:#f9e9e6;color:var(--red)}.small-flow{margin-top:23px;color:var(--slate);font-size:15px}.small-flow>b{display:block;color:var(--teal);margin:8px 0}.small-flow code{display:block;background:#eef5f7;color:var(--teal);padding:14px;border-radius:7px;font-size:15px}.steps{padding:0;list-style:none;counter-reset:item}.steps li{display:flex;gap:18px;align-items:flex-start;padding:13px 0;border-bottom:1px solid var(--line)}.steps b{min-width:83px;font-size:15px}.steps span{font-size:14px;color:var(--slate)}.bottom-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:23px}.bottom-grid>div{display:flex;gap:14px;font-size:14px;padding:16px 20px;background:#e8edf4;border-radius:8px}.bottom-grid span{color:var(--slate)}.comparison{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:23px 0}.comparison>div{border-radius:10px;background:#f2f5f8;padding:19px 16px}.comparison span,.comparison strong,.comparison b{display:block}.comparison span{font-size:10px;letter-spacing:1px;color:var(--slate)}.comparison strong{margin:12px 0;font-size:17px}.comparison b{font-size:13px}.amber-text{color:var(--amber)}.teal-text{color:var(--teal)}.policy-row{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding:13px 0;font-size:15px}.policy-row .outcome{font-size:13px;padding:7px 14px}.rag-layout{display:grid;grid-template-columns:2.1fr 1fr;gap:32px}table{border-collapse:collapse;width:100%;font-size:15px}th{text-align:left;font-weight:650;font-size:12px;color:var(--slate);padding:12px 14px;background:#e7edf4}td{padding:15px 14px;border-bottom:1px solid var(--line);background:#fff;vertical-align:middle}.condition-table td{padding-top:18px;padding-bottom:18px;font-size:17px}.retrieval{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin-top:25px}.retrieval span{padding:9px 12px;background:#e6edf5;font-size:13px;border-radius:7px}.retrieval b{font-size:17px;color:var(--slate);transform:rotate(-90deg)}.retrieval .emphasized{background:#dcedeb;color:var(--teal)}.metric-card{border-radius:12px;background:var(--navy);padding:20px;color:white}.metric-card b{font-size:42px;display:block;color:#83d6d1}.metric-card span{font-size:14px}.rag-layout aside p{font-size:15px;color:var(--slate)}.note{font-size:14px;background:#f8efd9;color:#80602c;padding:18px;border-radius:9px;margin:20px 0}.data-stamp{font-size:12px;color:var(--teal);margin:0 0 13px}.data-stamp>span{float:right;color:var(--slate);font-size:10px}.result-table{font-size:12px}.result-table th{font-size:10px;white-space:nowrap;padding:9px 12px}.result-table td{padding:10px 12px;white-space:nowrap}.result-table td:first-child{white-space:normal}.result-table small{display:block;font-size:9px;line-height:1.2;margin-top:4px;color:var(--slate)}.result-table .number{font-size:17px;font-weight:750;color:var(--teal)}.chart-heading{display:flex;justify-content:space-between;align-items:center;margin:21px 0 13px}.chart-heading h2{font-size:17px;margin:0}.chart-heading>span{font-size:11px;color:var(--slate)}.legend{display:inline-block;width:10px;height:10px;margin:0 5px 0 12px}.base{background:var(--base)}.guard{background:var(--guard)}.category-bars{display:grid;grid-template-columns:repeat(5,1fr);gap:17px}.bar-item{background:#fff;border:1px solid var(--line);padding:13px 11px;border-radius:9px}.bar-row{display:grid;grid-template-columns:1fr 36px;align-items:center;gap:5px;margin:8px 0}.bar-row>span{grid-column:1/3;font-size:9px;color:var(--slate)}.bar-track{background:#edf1f5;height:8px;border-radius:4px;overflow:hidden}.bar-track i{display:block;height:100%;border-radius:4px}.bar-row b{font-size:10px;text-align:right;white-space:nowrap}.category-change{display:block;font-size:10px;color:var(--teal);margin-top:10px}.fineprint{font-size:11px;line-height:1.6;margin-top:17px;color:var(--slate)}.empty{padding:25px;background:#fff4de;border:1px solid #eddbaf;color:#866731;font-size:16px;border-radius:10px}.challenge-grid{display:grid;grid-template-columns:1.43fr 1fr;gap:25px;margin-top:25px}.compact th{font-size:11px;padding:10px}.compact td{font-size:12px;padding:12px 10px}.negative{color:var(--red);font-weight:700}.positive{color:var(--teal);font-weight:700}.neutral{color:var(--slate)}.compact-card{padding:20px 22px}.compact-card h2{font-size:20px}.plain-list{padding-left:17px;margin:10px 0;color:var(--slate);font-size:13px}.plain-list li{margin:10px 0}.demo-title{font-size:20px;margin:26px 0 17px}.demo-sequence{display:grid;grid-template-columns:repeat(5,1fr);gap:14px}.demo-sequence>div{border:1px solid var(--line);border-radius:10px;background:white;padding:17px}.demo-sequence b{display:block;color:var(--teal);font-size:13px}.demo-sequence strong{display:block;font-size:17px;margin:10px 0}.demo-sequence span{font-size:12px;color:var(--slate)}.closing{display:flex;justify-content:space-between;align-items:center;margin-top:27px;padding:17px 20px;background:var(--navy);color:white;border-radius:10px}.closing code{font-size:15px}.closing span{font-size:12px;color:#c2d1e2}.toolbar{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:99;background:#142742ed;color:#e8eef5;border:1px solid #456079;border-radius:30px;padding:8px 14px;display:flex;gap:12px;align-items:center;box-shadow:0 3px 15px #12274330;font-size:12px;white-space:nowrap}.toolbar button{border:0;background:transparent;color:inherit;cursor:pointer;padding:4px 8px;font-size:12px}.toolbar button:hover,.toolbar button:focus-visible{background:#35506d;border-radius:12px}.toolbar .hint{color:#8ca6bf;border-left:1px solid #456079;padding-left:12px}body.present .slide:not(.active){display:none}
@media screen and (max-width:1160px){.deck{width:1122px;transform-origin:top left;margin:0}.toolbar{bottom:10px}.slide{margin-left:0}.toolbar .hint{display:none}}
@page{size:A4 landscape;margin:0}
@media print{html,body{width:297mm;background:white;margin:0!important;padding:0!important;font-size:16px;-webkit-print-color-adjust:exact;print-color-adjust:exact}.deck{padding:0;margin:0;width:auto;transform:none!important}.slide,body.present .slide:not(.active){display:flex!important;width:297mm;height:210mm;min-height:210mm;max-height:210mm;margin:0;box-shadow:none;break-after:page;page-break-after:always;break-inside:avoid}.slide:last-child{break-after:auto;page-break-after:auto}.toolbar{display:none!important}a{color:inherit;text-decoration:none}}
'''

SCRIPT = r'''
(() => {
  const slides = [...document.querySelectorAll('.slide')];
  let index = 0;
  const current = document.querySelector('#current');
  const allButton = document.querySelector('#all');
  const show = (n) => {
    index = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach((slide, i) => slide.classList.toggle('active', i === index));
    current.textContent = `${index + 1} / ${slides.length}`;
    if (!document.body.classList.contains('present')) slides[index].scrollIntoView({behavior:'smooth', block:'start'});
  };
  const toggleAll = () => {
    const present = document.body.classList.toggle('present');
    allButton.textContent = present ? '显示全部' : '逐页展示';
    if (present) window.scrollTo(0, 0);
    show(index);
  };
  document.body.classList.add('present');
  document.querySelector('#prev').addEventListener('click', () => show(index - 1));
  document.querySelector('#next').addEventListener('click', () => show(index + 1));
  allButton.addEventListener('click', toggleAll);
  document.querySelector('#print').addEventListener('click', () => window.print());
  document.addEventListener('keydown', event => {
    if (event.key === 'ArrowRight' || event.key === 'PageDown' || event.key === ' ') { event.preventDefault(); show(index + 1); }
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') { event.preventDefault(); show(index - 1); }
    if (event.key === 'Home') { event.preventDefault(); show(0); }
    if (event.key === 'End') { event.preventDefault(); show(slides.length - 1); }
    if (event.key.toLowerCase() === 'a') toggleAll();
  });
  const fit = () => {
    const deck = document.querySelector('.deck');
    if (window.innerWidth < 1160) {
      const scale = Math.max(.25, (window.innerWidth - 12) / 1122);
      deck.style.transform = `scale(${scale})`;
      document.body.style.minHeight = `${794 * scale + 105}px`;
    } else { deck.style.transform = ''; document.body.style.minHeight = ''; }
  };
  window.addEventListener('resize', fit);
  fit(); show(0);
})();
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'docs'/'面试汇报.html')
    args = parser.parse_args()
    summary = read_json(ROOT/'results'/'summary.json')
    challenge = read_json(ROOT/'results'/'archive_120'/'summary_challenge_kimi.json')
    html = ('<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>经纬 · 可信座舱 — 面试汇报</title><style>' + STYLE + '</style></head><body>'
            '<main class="deck">' + make_deck(summary, challenge) + '</main>'
            '<nav class="toolbar" aria-label="幻灯片导航"><button id="prev" aria-label="上一页">← 上一页</button>'
            '<span id="current" aria-live="polite">1 / 9</span><button id="next" aria-label="下一页">下一页 →</button>'
            '<button id="all">显示全部</button><button id="print">打印 / PDF</button>'
            '<span class="hint">← → 切页 · A 全部</span></nav><script>' + SCRIPT + '</script></body></html>')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding='utf-8')
    print(f'已生成 {args.output}：9 页；主实验 {len(groups(summary, "kimi"))} 组；历史挑战 {len(groups(challenge, "kimi"))} 组。')


if __name__ == '__main__':
    main()
