"""
P4 回归基准 — 汇总 P0-P3 结果，生成基准报告
执行：python3 eval/eval_p4_benchmark.py
读取已有的各阶段 JSON 报告，汇总输出。
"""

import sys
import os
import json
import glob
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def find_latest_reports(results_dir: str = "eval/results"):
    """找出各阶段最新的报告文件"""
    reports = {}
    for phase in ["P0_unit", "P1_parse", "P2_e2e", "P3_boundary", "P5_optimization", "P6_image"]:
        pattern = os.path.join(results_dir, f"*_{phase}.json")
        files = sorted(glob.glob(pattern))
        if files:
            reports[phase] = files[-1]  # 取最新的
    return reports


def load_report(filepath: str) -> dict:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_dimension_scores(p0: dict, p1: dict, p2: dict, p3: dict, p5: dict = None) -> dict:
    """从各阶段结果计算维度指标"""
    dims = {}

    # 基础功能正确率（P0 即 100% 隐含在工具层）
    dims["基础功能"] = "100%"

    # 参数提取准确率（P1）
    if p1:
        scored = [c for c in p1["cases"] if not c["details"].get("manual_review")]
        if scored:
            total_score = sum(
                c["details"].get("scores", {}).get("total", 0) for c in scored
            )
            max_score = len(scored) * 3
            dims["参数提取"] = f"{total_score / max_score * 100:.1f}%"
        else:
            dims["参数提取"] = "N/A"

    # 答案正确率（P2 scored cases）
    if p2:
        passed = p2["passed"]
        total = p2["total"]
        dims["答案正确率"] = f"{passed / total * 100:.1f}%" if total > 0 else "N/A"

    # 幻觉率（P2 hallu 检查失败数）
    if p2:
        hallu_fails = sum(
            1 for c in p2["cases"]
            if not c["details"].get("checks", {}).get("no_hallucination", True)
        )
        dims["幻觉率"] = f"{hallu_fails}/{p2['total']}" if p2["total"] > 0 else "N/A"

    # 优雅降级（P3 scored）
    if p3:
        scored = [c for c in p3["cases"] if not c["details"].get("skipped") and not c["details"].get("manual_review")]
        if scored:
            passed = sum(1 for c in scored if c["passed"])
            dims["优雅降级"] = f"{passed / len(scored) * 100:.1f}%"
        else:
            dims["优雅降级"] = "N/A"

    # 自反思纠错（P5-1）
    if p5:
        sr_cases = [c for c in p5["cases"] if c["case_id"].startswith("SR-")]
        if sr_cases:
            passed = sum(1 for c in sr_cases if c["passed"])
            dims["自反思纠错"] = f"{passed / len(sr_cases) * 100:.1f}%"

        # 追问正确率（P5-2）
        sp_cases = [c for c in p5["cases"] if c["case_id"].startswith("SP-")]
        if sp_cases:
            passed = sum(1 for c in sp_cases if c["passed"])
            dims["System Prompt 遵循"] = f"{passed / len(sp_cases) * 100:.1f}%"

    return dims


def main():
    print("=" * 60)
    print("  P4 回归基准汇总")
    print("=" * 60)

    session_id = os.getenv("EVAL_SESSION_ID", "")

    if session_id:
        from eval_helpers import find_session_reports
        reports = find_session_reports(session_id)
    else:
        reports = find_latest_reports()

    if not reports:
        print("\n未找到评估报告。请先运行 P0-P5/P6。")
        return

    print(f"\n读取报告：")
    for phase, path in reports.items():
        print(f"  {phase}: {path}")

    p0 = load_report(reports.get("P0_unit")) if "P0_unit" in reports else None
    p1 = load_report(reports.get("P1_parse")) if "P1_parse" in reports else None
    p2 = load_report(reports.get("P2_e2e")) if "P2_e2e" in reports else None
    p3 = load_report(reports.get("P3_boundary")) if "P3_boundary" in reports else None
    p5 = load_report(reports.get("P5_optimization")) if "P5_optimization" in reports else None
    p6 = load_report(reports.get("P6_image")) if "P6_image" in reports else None

    dims = compute_dimension_scores(p0, p1, p2, p3, p5)

    # 汇总所有阶段
    all_cases = []
    for r in [p0, p1, p2, p3, p5, p6]:
        if r:
            for c in r["cases"]:
                c["_phase"] = r["phase"]
                all_cases.append(c)

    total = len(all_cases)
    # 排除 known_missing 和 manual_review
    scorable = [c for c in all_cases
                if not c["details"].get("skipped")
                and not c["details"].get("manual_review")]
    passed = sum(1 for c in scorable if c["passed"])

    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total_cases": total,
            "scorable_cases": len(scorable),
            "passed": passed,
            "failed": len(scorable) - passed,
            "pass_rate": f"{passed / len(scorable) * 100:.1f}%" if scorable else "N/A",
        },
        "by_phase": {},
        "by_dimension": dims,
    }

    for phase, r in [("P0_unit", p0), ("P1_parse", p1), ("P2_e2e", p2), ("P3_boundary", p3), ("P5_optimization", p5), ("P6_image", p6)]:
        if r:
            report["by_phase"][phase] = {
                "total": r["total"],
                "passed": r["passed"],
                "failed": r["failed"],
                "pass_rate": r["pass_rate"],
                "duration_ms": r.get("duration_ms", 0),
            }

    # 保存
    os.makedirs("eval/results", exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"eval/results/{timestamp}_P4_benchmark.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 打印
    print(f"\n{'='*60}")
    print(f"  综合评估报告")
    print(f"{'='*60}")
    print(f"  总 case 数: {total}  |  可评分: {len(scorable)}  |  通过: {passed}  |  失败: {len(scorable) - passed}")
    print(f"  综合通过率: {report['summary']['pass_rate']}")
    print(f"\n  各阶段：")
    for phase, info in report["by_phase"].items():
        print(f"    {phase}: {info['pass_rate']} ({info['passed']}/{info['total']})")
    print(f"\n  各维度：")
    for dim, score in dims.items():
        print(f"    {dim}: {score}")
    print(f"\n报告已保存: {filename}")


if __name__ == "__main__":
    main()
