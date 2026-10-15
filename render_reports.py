#!/usr/bin/env python3
"""Render the Kimi before/after report from saved results; never predict scores."""
from collections import Counter
from pathlib import Path
import csv
import html
import json

ROOT = Path(__file__).resolve().parent
R = ROOT / "results"
CATEGORIES = [("ambiguity", "歧义消解"), ("tool_calling", "工具调用"),
              ("capability", "能力边界"), ("safety", "安全策略"), ("rag", "手册问答")]
NAMES = {"baseline": "方案前（简化对照）", "guarded": "方案后（可信执行）"}


def read(name):
    path = R / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def trials(name):
    path = R / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def rate(group):
    return group["passed"] / group["total"] if group.get("total") else 0


def score(group):
    return f"{rate(group):.2%}（{group.get('passed', 0)}/{group.get('total', 0)}）"


def main():
    summary = read("summary.json")
    pair = {g["mode"]: g for g in summary.get("groups", [])
            if g.get("provider") == "kimi" and g.get("mode") in NAMES}
    if set(pair) != set(NAMES):
        raise SystemExit("尚无完整的 Kimi 方案前/后汇总；不使用 offline 或历史分数填补。")
    groups = [pair[mode] for mode in NAMES]
    cases, repeats = summary.get("cases", "未知"), summary.get("repeats", "未知")
    before, after = pair["baseline"], pair["guarded"]
    category_scope = "、".join(f"{label} {summary.get('cases_per_category', {}).get(key, '未记录')} 例" for key, label in CATEGORIES)
    delta = 100 * (rate(after) - rate(before))
    lines = ["# 实测结果与可复现证据", "",
             f"生成：{summary.get('generated_at', '未知')}。源码、语料与用例指纹见 [summary.json](summary.json)。", "",
             "本页只展示真实 Kimi 的方案前/后比较；数值来自保存的逐例结果，未预填成绩。所有车辆动作均为模拟。", "",
             f"## 主实验：{cases} 个开发可见场景 × {repeats} 次", "",
             f"**整体准确率：{score(before)} → {score(after)}，变化 {delta:+.2f} 个百分点。**", "",
             "这里的准确率是完整用例通过率：正确执行、正确澄清、正确拒绝或正确故障检出都按各例预定判据评分，多轮必须所有必要断言通过。", "",
             "方案前（简化对照）关闭本次执行/证据层可切换的新增检查，但保留共用模型提示、基础工具合同、上游 VAL 与确认；方案后（可信执行）启用新增检查。不是完整原项目与新项目的跑分，也不是模型微调前后。", "",
             "同一真实 Kimi 候选分别送入两组独立模拟车辆；多轮计划参考方案后分支历史，不是两个独立 Agent 的端到端比较。", "",
             "|类别|方案前准确率|方案后准确率|变化（百分点）|", "|---|---:|---:|---:|"]
    comparisons = [("整体", before, after)]
    for key, label in CATEGORIES:
        comparisons.append((label, before.get("categories", {}).get(key, {}), after.get("categories", {}).get(key, {})))
    for label, b, g in comparisons:
        lines.append(f"|{label}|{score(b)}|{score(g)}|{100*(rate(g)-rate(b)):+.2f}|")
    lines += ["", f"{cases} 个不同用例（{category_scope}），各重复 {repeats} 次；方案前 {before['total']} 次、方案后 {after['total']} 次，共 {before['total']+after['total']} 条组级记录。重复不增加同等数量的独立语义场景，两组又共享模型候选，因此组级记录数不等于独立模型调用数。", "",
              "新增用例与旧用例均为开发者可见的回归集，不是独立盲测。offline 仅保留作开发回归，不纳入本页主成绩。", "",
              "## 运行细节", "", "|实验组|全部重复均通过的场景比例|平均处理延迟|P95|模型错误次数|", "|---|---:|---:|---:|---:|"]
    for group in groups:
        lines.append(f"|{NAMES[group['mode']]}|{group['consistent_rate']:.2%}|{group['avg_latency_ms']:.1f} ms|{group['p95_latency_ms']:.1f} ms|{group.get('model_errors', 0)}|")
    usage = summary.get("usage", {}).get("kimi", {})
    model_names = sorted({g.get("model", "未记录") for g in groups})
    lines += ["", f"实际模型：{' / '.join(model_names)}。输入 {usage.get('prompt_tokens', 0):,} Token，输出 {usage.get('completion_tokens', 0):,} Token，总计 {usage.get('total_tokens', 0):,} Token。两组共享候选的 Token 不重复相加。服务未提供计价，未估算货币成本。", "",
              f"运行期间源码变动标记：`{str(summary.get('source_changed_during_run', 'unknown')).lower()}`；正式结果应为 `false`。", "",
              "## 本轮失败与边界", "",
              "以下按实际失败记录生成，包含状态、原话与断言。`missing_fact` 表示共同文本判据未覆盖所需条件，不等于专家完成了全答案事实审查；仍需对照源手册人工复核。", ""]
    records = trials("trials_kimi.jsonl")
    failed = [r for r in records if not r["passed"]]
    for mode in NAMES:
        errors = [r for r in failed if r["mode"] == mode]
        no_calls = sum(not any(t["response"].get("calls") for t in r["turns"]) for r in errors)
        counts = Counter(r["category"] for r in errors)
        detail = "、".join(f"{label} {counts[key]} 次" for key, label in CATEGORIES if counts[key]) or "无失败记录"
        lines.append(f"- {NAMES[mode]}：{len(errors)} 次用例失败（{detail}），其中 {no_calls} 次未调用车辆工具。未调用也可能是未完成合理请求；失败不全等于危险动作。")
    seen = set()
    counts = Counter((r["id"], r["mode"]) for r in failed)
    for record in failed:
        key = (record["id"], record["mode"])
        if key in seen:
            continue
        seen.add(key)
        failed_turn = next((t for t in record["turns"] if t.get("errors")), record["turns"][-1])
        errors = "；".join(failed_turn.get("errors", [])) or "详见完整逐例记录"
        lines.append(f"- **{record['id']} / {NAMES[record['mode']]} / {counts[key]} 次**：{failed_turn['text']} → `{failed_turn['response']['status']}`；判据：`{errors}`。其他轮次差异见原始记录。")
    if not failed:
        lines.append("本轮保存样本无失败；这不代表未覆盖输入同样正确。")
    lines += ["", "## 历史补充：120 例阶段的挑战与消融", "",
              f"此前 120 例阶段的结果保存在 [archive_120](archive_120/)。该阶段的 15 例挑战、消融、调试采样与旧主实验都不混入本轮 {cases} 例成绩，也不作为本轮的独立验证集。", "",
              "- [历史 Kimi 挑战汇总](archive_120/summary_challenge_kimi.json) / [逐例记录](archive_120/trials_challenge_kimi.jsonl)",
              "- [历史模块消融](archive_120/ablation.md) / [完整记录](archive_120/ablation.json)", "",
              "历史挑战由同一团队在当时引擎冻结后编写，仍不是第三方盲测。历史消融明确注入错误计划或故障，不能解释为模型自然失误；小语料未证明字符 TF-IDF 支路单独带来收益。", "",
              "## 验证与产物", "",
              "- [主实验逐例记录](trials_kimi.jsonl) / [汇总](summary.json) / [CSV](metrics.csv)",
              "- [单元/集成测试原始日志](unit_tests.txt)",
              "- [本轮评测页检查](benchmark_browser.json) / [历史完整交互检查](archive_120/browser_checks.json) / [历史浏览器 Kimi 请求](archive_120/kimi_browser.json)",
              "- [环境版本](environment.json) / [源码改动目录](source_changes.json) / [密钥扫描](security_check.json)", "",
              "浏览器和机制测试各自保留执行范围，不把历史检查次数当作本轮新跑次数。开发中断采样和 smoke 记录只作调试证据，不进入主成绩。", "",
              "## 可以说与不能说", "",
              "可以说：在这些开发可见输入及可重放故障条件下，比较新增执行/证据约束对完整用例通过率的影响；报告改善、持平和退步。", "",
              "不能说：解决任意自然语言歧义、证明实车绝对安全、优于完整上游、取得官方 CAR-bench 成绩、证明混合检索独自带来全部收益，或实现跨进程恰好一次执行。", "",
              "下一步应扩大独立口语、多轮和真实手册评估，区分正确拒绝与不必要拒绝，并对已观察失败重新设计验证集。"]
    (R / "实测结果.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (R / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=["name", "provider", "mode", "total", "passed", "pass_rate", "consistent_rate", "avg_latency_ms", "p95_latency_ms"])
        writer.writeheader()
        for group in groups:
            row = {key: group.get(key) for key in writer.fieldnames}
            row.update(name=NAMES[group["mode"]], pass_rate=rate(group))
            writer.writerow(row)
    cards = "".join(f'<article><span>{NAMES[g["mode"]]}</span><b>{rate(g):.2%}</b><small>{g["passed"]}/{g["total"]} 次通过</small></article>' for g in groups)
    rows = "".join(f'<tr><td>{label}</td><td>{rate(b):.2%}</td><td>{rate(g):.2%}</td><td>{100*(rate(g)-rate(b)):+.2f}</td></tr>' for label, b, g in comparisons)
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>经纬可信座舱 · 实测报告</title><style>body{{font:16px/1.7 system-ui,sans-serif;background:#f2f5f7;color:#1b3042;max-width:960px;margin:32px auto;padding:24px}}h1{{font-size:32px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}}article{{background:white;padding:24px;border-radius:16px}}article b{{display:block;font-size:38px}}small,p{{color:#607080}}a{{color:#326a5e}}table{{width:100%;border-collapse:collapse;background:white;margin:24px 0}}td,th{{padding:14px;text-align:right;border-bottom:1px solid #e6ecee}}td:first-child,th:first-child{{text-align:left}}pre{{white-space:pre-wrap;word-break:break-word;background:white;padding:24px;font:14px/1.8 system-ui}}summary{{cursor:pointer}}</style><header><small>MERIDIAN · COCKPIT LAB</small><h1>方案前后，准确率怎样变化</h1><p>真实 Kimi · {cases} 个开发可见用例 × {repeats} 次 · 同候选配对 · 模拟车辆</p></header><main><div class="grid">{cards}<article><span>整体变化</span><b>{delta:+.2f}</b><small>个百分点</small></article></div><table><thead><tr><th>类别</th><th>方案前</th><th>方案后</th><th>变化 / 百分点</th></tr></thead><tbody>{rows}</tbody></table><p>准确率指完整用例通过率。方案前为关闭部分新增检查的简化对照，不代表完整原项目。<a href="实测结果.md">完整报告与失败</a> · <a href="summary.json">原始汇总</a> · <a href="metrics.csv">CSV</a></p><details><summary>查看实验口径、逐例失败与历史补充</summary><pre>{html.escape(chr(10).join(lines))}</pre></details></main></html>'''
    (R / "report.html").write_text(page, encoding="utf-8")
    print("Rendered Kimi before/after results/实测结果.md, metrics.csv, report.html.")


if __name__ == "__main__":
    main()
