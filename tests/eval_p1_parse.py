"""
P1 工具参数提取测试 — 验证 _parse_attrs_from_query 的属性和别名提取
执行：python3 tests/eval_p1_parse.py
需 LLM API 调用，约 20 个 case，预计耗时 30s
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_helpers import (
    EvalRecorder, save_report, print_summary, score_param_extraction
)


def run_p1(recorder: EvalRecorder):
    from config import Settings
    from tools.multi_platform_tools import _parse_attrs_from_query

    s = Settings()
    client, model = s.client, s.model

    # ── P1-1: 属性提取 ──────────────────────────────────────────────────
    attr_cases = [
        ("AP-01", "黑色 iPhone 15 256GB",  {"product_name": "iPhone 15", "color": "黑色", "memory": "256GB"}),
        ("AP-02", "iPhone 15",             {"product_name": "iPhone 15", "color": "", "memory": ""}),
        ("AP-03", "小米14 白色",            {"product_name": "小米14", "color": "白色", "memory": ""}),
        ("AP-04", "小米14 512GB 绿色",      {"product_name": "小米14", "color": "绿色", "memory": "512GB"}),
        ("AP-05", "AirPods Pro 2",         {"product_name": "AirPods Pro 2", "color": "", "memory": ""}),
        ("AP-06", "iPad Pro 11寸",         {"product_name": "iPad Pro", "color": "", "memory": ""}),
        ("AP-07", "128GB 小米平板6 黑色",   {"product_name": "小米平板6", "color": "黑色", "memory": "128GB"}),
    ]

    print("\n--- P1-1: 属性提取 ---")
    for case_id, query, expected in attr_cases:
        actual = _parse_attrs_from_query(query, client, model)
        scores = score_param_extraction(actual, expected)
        passed = scores["total"] == 3
        recorder.record(case_id, passed, {
            "input": query,
            "expected": expected,
            "actual": {k: actual.get(k, "") for k in ["product_name", "color", "memory"]},
            "scores": scores,
        })
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: {query} → {actual['product_name']} | {actual['color']} | {actual['memory']}")

    # ── P1-2: 别名改写 ──────────────────────────────────────────────────
    alias_cases = [
        ("AL-01", "水果手机 15 黑色",   {"product_name": "iPhone 15", "color": "黑色", "memory": ""}),
        ("AL-02", "苹果手机 256GB",     {"product_name": "iPhone", "color": "", "memory": "256GB"}),
        ("AL-03", "水果手表",           {"product_name": "Apple Watch", "color": "", "memory": ""}),
        ("AL-04", "苹果平板",           {"product_name": "iPad", "color": "", "memory": ""}),
        ("AL-05", "ip15 白色 128g",    {"product_name": "iPhone 15", "color": "白色", "memory": "128GB"}),
        ("AL-06", "米14 绿色",          {"product_name": "小米14", "color": "绿色", "memory": ""}),
        ("AL-07", "苹果手机 15 黑",     {"product_name": "iPhone 15", "color": "黑色", "memory": ""}),
    ]

    print("\n--- P1-2: 别名改写 ---")
    for case_id, query, expected in alias_cases:
        actual = _parse_attrs_from_query(query, client, model)
        scores = score_param_extraction(actual, expected)
        passed = scores["total"] == 3
        recorder.record(case_id, passed, {
            "input": query,
            "expected": expected,
            "actual": {k: actual.get(k, "") for k in ["product_name", "color", "memory"]},
            "scores": scores,
        })
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: {query} → {actual['product_name']} | {actual['color']} | {actual['memory']}")

    # ── P1-3: 歧义输入 ──────────────────────────────────────────────────
    # 这类 case 不自动评分，记录输出供人工检查
    ambiguous_cases = [
        ("AM-01", "苹果", "品牌或品类歧义"),
        ("AM-02", "手机", "品类而非具体商品"),
        ("AM-03", "便宜的", "无商品名"),
    ]

    print("\n--- P1-3: 歧义输入（人工检查）---")
    for case_id, query, note in ambiguous_cases:
        actual = _parse_attrs_from_query(query, client, model)
        recorder.record(case_id, True, {  # 歧义 case 始终 "通过"（只记录不评分）
            "input": query,
            "actual": {k: actual.get(k, "") for k in ["product_name", "color", "memory"]},
            "note": note,
            "manual_review": True,
        })
        print(f"  ? {case_id}: {query} → {actual['product_name']} | {actual['color']} | {actual['memory']} ({note})")


def main():
    print("=" * 60)
    print("  P1 工具参数提取测试（LLM 单次调用）")
    print("=" * 60)

    recorder = EvalRecorder("P1_parse")
    run_p1(recorder)

    summary = recorder.summary()

    # 歧义 case 不算入通过率
    scored_cases = [c for c in summary["cases"] if not c["details"].get("manual_review")]
    scored_passed = sum(1 for c in scored_cases if c["passed"])
    summary["scored_total"] = len(scored_cases)
    summary["scored_passed"] = scored_passed
    summary["scored_pass_rate"] = f"{scored_passed / len(scored_cases) * 100:.1f}%" if scored_cases else "N/A"

    print_summary(summary)
    if scored_cases:
        print(f"  评分 case 通过率: {summary['scored_pass_rate']} ({scored_passed}/{len(scored_cases)})")

    filename = save_report("P1_parse", summary)
    print(f"报告已保存: {filename}")

    return len([c for c in scored_cases if not c["passed"]]) == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
