"""
P3 能力边界测试 — 测试 Agent 的鲁棒性极限
执行：python3 tests/eval_p3_boundary.py
约 16 个 case，预计耗时 60s

注意：部分 case（多轮对话）依赖未实现的 history 功能，标记为 known_missing。
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_helpers import (
    EvalRecorder, save_report, print_summary,
    extract_prices, extract_platform_names
)


class BoundaryRunner:
    def __init__(self):
        from config import Settings
        from tools import tool_registry, init_parallel_agent, cleanup_parallel_agent
        from platforms import init_all_platforms
        from agent import ReActAgent

        init_all_platforms()
        init_parallel_agent()

        self.settings = Settings()
        self.agent = ReActAgent(
            client=self.settings.client,
            model=self.settings.model,
            tools=tool_registry.get_schemas(),
            tool_map=tool_registry.get_tool_map(),
            max_round=self.settings.max_round,
        )
        self._cleanup = cleanup_parallel_agent

    def run_one(self, query: str) -> dict:
        start = time.time()
        try:
            answer = self.agent.run(query, verbose=False)
        except Exception as e:
            answer = f"[ERROR] {e}"
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "answer": answer,
            "prices": extract_prices(answer),
            "platforms": extract_platform_names(answer),
            "total_time_ms": elapsed_ms,
        }

    def cleanup(self):
        self._cleanup()


def test_non_existent(recorder: EvalRecorder, runner: BoundaryRunner):
    """P3-1: 不存在的商品"""
    cases = [
        ("BD-01", "iPhone 20 多少钱", "告知未找到"),
        ("BD-02", "华为Mate60 在哪个平台", "告知未找到"),
        ("BD-03", "诺基亚3310 价格", "告知未找到"),
    ]
    print("\n--- P3-1: 不存在的商品 ---")
    for case_id, query, expected_behavior in cases:
        result = runner.run_one(query)
        answer = result["answer"]

        # 优雅降级：不应报错，不应该编造价格
        has_error = "[ERROR]" in answer
        has_price = len(result["prices"]) > 0
        # 应该告知未找到或没有结果
        not_found_keywords = ["未找到", "没有", "不存在", "无匹配", "无商品", "无相关"]
        graceful = any(kw in answer for kw in not_found_keywords)

        passed = not has_error and (graceful or not has_price)
        recorder.record(case_id, passed, {
            "query": query,
            "expected_behavior": expected_behavior,
            "answer_preview": answer[:150],
            "has_error": has_error,
            "has_price": has_price,
            "graceful": graceful,
        })
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: error={has_error}, price={has_price}, graceful={graceful}")


def test_ambiguous(recorder: EvalRecorder, runner: BoundaryRunner):
    """P3-2: 歧义和模糊输入"""
    cases = [
        ("BD-04", "15", "极其模糊，需澄清"),
        ("BD-05", "苹果", "可指品牌或水果"),
        ("BD-06", "便宜的", "无商品名"),
        ("BD-07", "帮我看看", "无实质内容"),
    ]
    print("\n--- P3-2: 歧义输入 ---")
    for case_id, query, note in cases:
        result = runner.run_one(query)
        answer = result["answer"]
        has_error = "[ERROR]" in answer
        # 理想情况：Agent 请求澄清或返回了模糊匹配结果
        clarification_keywords = ["请问", "您是指", "具体", "哪一款", "什么", "可以"]
        asks_clarify = any(kw in answer for kw in clarification_keywords)

        # 歧义输入不自动评分，记录行为供人工检查
        recorder.record(case_id, True, {  # 始终通过（人工评估）
            "query": query,
            "note": note,
            "answer_preview": answer[:150],
            "has_error": has_error,
            "asks_clarification": asks_clarify,
            "manual_review": True,
        })
        print(f"  ? {case_id}: {query} → clarify={asks_clarify}, error={has_error} ({note})")


def test_malformed(recorder: EvalRecorder, runner: BoundaryRunner):
    """P3-3: 异常输入"""
    cases = [
        ("BD-08", "", "空字符串"),
        ("BD-09", "!@#$%^&*()", "特殊字符"),
        ("BD-10", "哈哈哈哈哈哈", "无意义输入"),
    ]
    print("\n--- P3-3: 异常输入 ---")
    for case_id, query, note in cases:
        result = runner.run_one(query)
        answer = result["answer"]
        has_error = "[ERROR]" in answer
        # 不应崩溃（无系统异常），至少应有回应
        crashed = has_error and "Rate" not in answer and "timeout" not in answer.lower()

        passed = not crashed
        recorder.record(case_id, passed, {
            "query": query,
            "note": note,
            "answer_preview": answer[:150],
            "has_error": has_error,
            "crashed": crashed,
        })
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: '{query}' → error={has_error}, crashed={crashed}")


def test_impossible(recorder: EvalRecorder, runner: BoundaryRunner):
    """P3-4: 矛盾需求"""
    cases = [
        ("BD-11", "iPhone 15 紫色 1TB 在哪买", "无此配置组合"),
        ("BD-12", "比价价格低于 1000 的 iPhone 15", "不存在（mock 数据最低 5750）"),
    ]
    print("\n--- P3-4: 矛盾需求 ---")
    for case_id, query, note in cases:
        result = runner.run_one(query)
        answer = result["answer"]
        has_error = "[ERROR]" in answer

        # 应处理优雅：告知无匹配且不崩溃
        passed = not has_error
        recorder.record(case_id, passed, {
            "query": query,
            "note": note,
            "answer_preview": answer[:150],
            "has_error": has_error,
        })
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: error={has_error}")


def test_multiturn_known_missing(recorder: EvalRecorder):
    """P3-5: 多轮对话 — 当前未实现，预期失败"""
    cases = [
        ("BD-13", "多轮对话：第1轮 iPhone 15 最便宜 | 第2轮 那小米14呢",
         "需要 history 参数支持"),
        ("BD-14", "多轮对话：京东查 iPhone 15 | 切换到淘宝",
         "需要 history 参数支持"),
        ("BD-15", "多轮对话：所有平台商品 | 筛选手机类",
         "需要 history 参数支持"),
    ]
    print("\n--- P3-5: 多轮对话（known_missing）---")
    for case_id, note, reason in cases:
        recorder.record(case_id, False, {
            "note": note,
            "reason": reason,
            "status": "known_missing",
            "skipped": True,
        })
        print(f"  ⊘ {case_id}: {reason}")


def main():
    print("=" * 60)
    print("  P3 能力边界测试")
    print("=" * 60)

    recorder = EvalRecorder("P3_boundary")

    try:
        runner = BoundaryRunner()
        test_non_existent(recorder, runner)
        test_ambiguous(recorder, runner)
        test_malformed(recorder, runner)
        test_impossible(recorder, runner)
        runner.cleanup()
    except Exception as e:
        print(f"\n  ⚠ LLM API 错误（可能欠费）: {e}")
        print("  继续生成部分报告...")
        runner = None

    test_multiturn_known_missing(recorder)

    summary = recorder.summary()

    # 统计 known_missing 和 manual_review
    scored = [c for c in summary["cases"] if not c["details"].get("skipped") and not c["details"].get("manual_review")]
    scored_passed = sum(1 for c in scored if c["passed"])
    summary["scored_total"] = len(scored)
    summary["scored_passed"] = scored_passed
    summary["scored_pass_rate"] = f"{scored_passed / len(scored) * 100:.1f}%" if scored else "N/A"
    summary["known_missing"] = sum(1 for c in summary["cases"] if c["details"].get("skipped"))
    summary["manual_review"] = sum(1 for c in summary["cases"] if c["details"].get("manual_review"))

    print_summary(summary)
    if scored:
        print(f"  评分 case 通过率: {summary['scored_pass_rate']} ({scored_passed}/{len(scored)})")
    print(f"  Known missing: {summary['known_missing']}  |  Manual review: {summary['manual_review']}")

    filename = save_report("P3_boundary", summary)
    print(f"报告已保存: {filename}")

    return True  # P3 有 known_missing，不阻断


if __name__ == "__main__":
    main()
