#!/usr/bin/env python3
"""Render reports from saved results only. Never contains expected scores."""
from pathlib import Path
import csv
import html
import json

ROOT = Path(__file__).resolve().parent
R = ROOT / "results"


def read(name):
    p = R / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def trials(name):
    p = R / name
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def main():
    s = read("summary.json")
    groups = s.get("groups", [])
    lines = ["# 实测结果与可复现证据", "", f"生成：{s.get('generated_at', '未知')}。源码、语料与用例指纹见 [summary.json](summary.json)。",
             "", "本报告由保存的逐例结果生成，未预填成绩。实验对象是新增本地适配层，所有车辆动作均为模拟。", "",
             "## 主实验：120个开发回归场景 × 3次", "",
             "同一模型候选分别送入简化对照与可信执行；两组拥有独立车辆状态。多轮计划参考可信分支历史，不是两个独立Agent端到端跑分。",
             "", "|实验组|通过次数|通过率|全部3次均通过的场景比例|平均处理延迟|P95|",
             "|---|---:|---:|---:|---:|---:|"]
    for g in groups:
        lines.append(f"|{g['name']}|{g['passed']}/{g['total']}|{g['pass_rate']:.1%}|{g['consistent_rate']:.1%}|{g['avg_latency_ms']:.1f} ms|{g['p95_latency_ms']:.1f} ms|")
    lines += ["", "离线重复是确定性回归，不代表模型随机稳定性。Kimi分组包含实际API请求；同一次模型请求成本在两组之间共享，不能将两组Token相加。", "",
              "### 五类分项", "", "|实验组|歧义消解|工具调用|能力边界|安全策略|手册问答|", "|---|---:|---:|---:|---:|---:|"]
    for g in groups:
        cells = [f"{g['categories'][c]['passed']}/{g['categories'][c]['total']}" for c in ['ambiguity','tool_calling','capability','safety','rag']]
        lines.append("|"+g["name"]+"|"+"|".join(cells)+"|")
    usage = s.get("usage", {}).get("kimi", {})
    lines += ["", "### 真实调用用量", "", f"主实验Kimi：输入 {usage.get('prompt_tokens', 0):,} Token，输出 {usage.get('completion_tokens', 0):,} Token，总计 {usage.get('total_tokens', 0):,} Token。模型名以各组model字段为准。服务未提供计费单价，未估算货币成本。调试、浏览器和挑战集调用单独记录。", "",
              "## 冻结后新增15个挑战表达", "", "这15例在引擎冻结后编写，结果没有用于继续调参；仍由同一项目团队编写，不是第三方盲测。允许出现保守拒绝和失败，不能只看预定义用例满分。", "",
              "|实验组|通过次数|通过率|3次均通过比例|", "|---|---:|---:|---:|"]
    challenges = []
    for name in ("summary_challenge_offline.json", "summary_challenge_kimi.json"):
        challenges.extend(read(name).get("groups", []))
    for g in challenges:
        lines.append(f"|{g['name']}|{g['passed']}/{g['total']}|{g['pass_rate']:.1%}|{g['consistent_rate']:.1%}|")
    records = trials("trials_kimi.jsonl")
    lines += ["", "## 失败与边界", "", "以下保留失败例。`missing_fact` 是共同文本判据没有覆盖所需条件，不等价于经过专家评审的全部事实错误；完整回答应与源手册一起复核。", ""]
    failed_guarded = [r for r in records if r["mode"] == "guarded" and not r["passed"]]
    invalid = [r for r in failed_guarded if r["id"] in {"TOO-015", "TOO-016", "TOO-017", "TOO-018"}]
    no_calls = sum(not any(t["response"].get("calls") for t in r["turns"]) for r in failed_guarded)
    if failed_guarded:
        lines += [f"主实验可信执行有 **{len(failed_guarded)} 次严格判据失败**，其中 {no_calls} 次没有调用车辆工具；不能将这些失败一律解读成危险动作。",
                  "", f"其中 {len(invalid)} 次来自越界开度/温度：系统没有执行，但返回 `clarify`、`unsupported` 或 `answered`，不满足预先规定的 `blocked` 状态。部分回答正确指出范围，部分却丢失具体拒绝理由、输出泛化介绍；这是状态归类和答复质量的真实缺口，未在看见成绩后放宽判据。另有按摩关闭请求被不必要地追问。",
                  "", "挑战集的可信执行失败集中于‘给后座透透气’、‘替我把汽车开回家’和含‘宝宝’的跨市场手册问句：没有触发动作，但泛化回答或追问不能满足澄清、能力拒绝和证据不足拒答的预期。当前规则对未覆盖口语的泛化有限。", ""]
    seen = set()
    for r in records + trials("trials_challenge_kimi.jsonl"):
        if r["passed"] or (r["id"],r["mode"]) in seen:
            continue
        seen.add((r["id"],r["mode"]))
        failed = next(t for t in r["turns"] if t["errors"])
        lines.append(f"- **{r['id']} / {r['mode']}**：{failed['text']} → `{failed['response']['status']}`；判据：`{'；'.join(failed['errors'])}`。")
    if not seen:
        lines.append("本轮所保存模型样本没有触发失败；这不代表未覆盖输入同样正确。")
    lines += ["", "## 模块消融", "", "见 [ablation.md](ablation.md) 和 [完整消融记录](ablation.json)。该组由脚本明确注入错误候选/故障，不能解释为模型自然失误。RAG去掉字符TF-IDF支路可能没有分数变化，要以实际表格为准。", "",
              "## 验证与产物", "",
              "- [单元/集成测试原始日志](unit_tests.txt)",
              "- [真实浏览器交互检查](browser_checks.json) / [浏览器Kimi请求](kimi_browser.json)",
              "- [Kimi主实验逐例记录](trials_kimi.jsonl) / [离线逐例记录](trials_offline.jsonl)",
              "- [Kimi挑战记录](trials_challenge_kimi.jsonl) / [离线挑战记录](trials_challenge_offline.jsonl)",
              "- [环境版本](environment.json) / [源码改动目录](source_changes.json) / [密钥扫描](security_check.json)",
              "- [座舱截图](screenshots/01_studio_desktop.png) / [真实Kimi截图](screenshots/09_kimi_live.png) / [移动布局](screenshots/08_studio_mobile.png)",
              "", "`development_partial_kimi.jsonl` 是修复读态问句及完善计划归档前中止的开发采样；`development_interrupted_kimi.jsonl` 是后续受运行会话中断影响的未完成采样。两者都不计入最终成绩；smoke记录仅用于接口验证。最终主实验必须满足 `source_changed_during_run=false`。", "",
              "## 可以说与不能说", "",
              "可以说：在这些冻结回归输入和可重放故障条件下，新增约束是否降低了特定错误；按位置读回能发现实际模拟状态与目标不一致；条件事实输出保留必要警告。",
              "", "不能说：解决了任意自然语言歧义、证明车辆绝对安全、优于完整上游、取得CAR-bench官方成绩、混合检索独自带来全部收益、实现跨进程恰好一次执行。",
              "", "下一步重点：扩大独立口语与多轮数据集，区分正确拒绝和不必要拒绝；给语义核对引入更可靠的证据解析；增加持久操作日志、真实信号与更大手册语料评估。"]
    (R/"实测结果.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    with (R/"metrics.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name","provider","mode","total","passed","pass_rate","consistent_rate","avg_latency_ms","p95_latency_ms"])
        writer.writeheader()
        writer.writerows({k:g.get(k) for k in writer.fieldnames} for g in groups)
    bars = "".join(f'<article><span>{html.escape(g["name"])}</span><b>{g["pass_rate"]:.1%}</b><div><i style="width:{g["pass_rate"]*100:.1f}%"></i></div><small>{g["passed"]}/{g["total"]} 次通过 · 一致率 {g["consistent_rate"]:.1%}</small></article>' for g in groups)
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>经纬可信座舱 · 实测报告</title><style>body{{font:16px/1.7 system-ui,sans-serif;background:#f2f5f7;color:#1b3042;max-width:1000px;margin:40px auto;padding:24px}}header{{border-top:6px solid #477869;padding:28px 0}}h1{{font-size:36px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}article{{background:white;padding:24px;border-radius:18px}}article b{{display:block;font-size:38px}}article div{{height:8px;background:#e6ecee;border-radius:8px;margin:12px 0}}i{{display:block;background:#477869;height:8px;border-radius:8px}}small{{color:#607080}}a{{color:#326a5e}}pre{{white-space:pre-wrap;word-break:break-word;background:white;padding:24px;border-radius:18px;font:14px/1.8 system-ui}}</style><header><small>MERIDIAN · COCKPIT LAB</small><h1>把可靠性，交给证据。</h1><p>真实Kimi调用 / 独立模拟车态 / 同计划配对 / 120个开发回归场景</p></header><main><div class="grid">{bars}</div><p>这是新增层的回归与消融结果，不是实车认证或官方Benchmark成绩。<a href="实测结果.md">阅读完整Markdown报告</a> · <a href="summary.json">原始汇总</a> · <a href="metrics.csv">下载CSV</a></p><pre>{html.escape(chr(10).join(lines))}</pre></main></html>'''
    (R/"report.html").write_text(page, encoding="utf-8")
    print("Rendered results/实测结果.md, metrics.csv, report.html from actual artifacts.")


if __name__ == "__main__":
    main()
