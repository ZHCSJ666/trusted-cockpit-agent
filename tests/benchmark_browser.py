"""Verify the report UI against the actual saved Kimi evaluation, without mocks."""
from pathlib import Path
import json
import re
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
REPORT = json.loads((ROOT / "results/summary.json").read_text())
GROUPS = {g["mode"]: g for g in REPORT["groups"] if g["provider"] == "kimi"}
BEFORE, AFTER = GROUPS["baseline"], GROUPS["guarded"]
OUT = ROOT / "results/screenshots"
CATEGORIES = {"ambiguity": "歧义澄清", "tool_calling": "可靠工具调用", "capability": "能力边界", "safety": "安全约束", "rag": "有据回答"}
checks, errors = [], []


def rate(group):
    return group["passed"] / group["total"] * 100


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    for width, height, filename in [(1440, 1100, "07_benchmark.png"), (390, 844, "11_benchmark_mobile.png")]:
        page = browser.new_page(viewport={"width": width, "height": height})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8787", wait_until="networkidle")
        page.get_by_role("button", name=re.compile("评测报告")).click()
        expect(page.get_by_role("heading", name="方案前后，准确率对比。")).to_be_visible()
        section = page.locator(".meridian-results")
        overview = page.get_by_label("总准确率对比")
        for mode, group in [("before", BEFORE), ("after", AFTER)]:
            expect(overview.locator(f".meridian-comparison-score.{mode} strong")).to_have_text(f"{rate(group):.2f}%")
            expect(overview.locator(f".meridian-comparison-score.{mode} p")).to_have_text(f"{group['passed']} / {group['total']} 次通过")
        delta = rate(AFTER) - rate(BEFORE)
        expected_delta = f"{delta:+.2f}" if delta > 0 else f"{delta:.2f}"
        assert expected_delta in overview.locator(".meridian-comparison-change strong").inner_text()
        for key, label in CATEGORIES.items():
            for mode, name in [("baseline", "方案前"), ("guarded", "方案后")]:
                g = GROUPS[mode]["categories"][key]
                expect(section.get_by_label(f"{label}，{name}准确率 {rate(g):.2f}%，{g['passed']} / {g['total']} 次通过", exact=True)).to_be_visible()
        assert f"{REPORT['cases']} 个用例" in section.inner_text()
        assert section.locator(".meridian-comparison-row").count() == 5
        assert "offline" not in section.inner_text().lower()
        assert "离线规则" not in section.inner_text()
        assert section.locator("pre").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        section.get_by_text("评测说明", exact=True).click()
        expect(section.get_by_text(AFTER["model"], exact=True)).to_be_visible()
        section.get_by_text("评测说明", exact=True).click()
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(OUT / filename), full_page=True)
        checks.append({"width": width, "accuracies": "matched saved trials", "category_comparisons": 10,
                       "visible_groups": 2, "offline_hidden": True, "overflow": False})
        page.close()
    browser.close()
assert not errors, errors
result = {"passed": True, "cases": REPORT["cases"], "repeats": REPORT["repeats"],
          "checks": checks, "page_errors": errors, "responses_mocked": False}
(ROOT / "results/benchmark_browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False))
