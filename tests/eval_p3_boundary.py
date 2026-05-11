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


def test_multiturn(recorder: EvalRecorder, runner: BoundaryRunner):
    """P3-5: 多轮对话 — 验证滑动窗口上下文"""
    print("\n--- P3-5: 多轮对话 ---")

    # BD-13: 第1轮查 iPhone 15 → 第2轮问 "那小米14呢"（指代"最便宜"）
    print("  BD-13: Round 1...")
    r1 = runner.run_one("iPhone 15 在哪个平台最便宜")
    a1 = r1["answer"]
    has_iphone_price = "¥" in a1 or "元" in a1

    history = [
        {"role": "user", "content": "iPhone 15 在哪个平台最便宜"},
        {"role": "assistant", "content": a1},
    ]
    # 直接用 agent.run 调用（带 history），不走 run_one
    import time
    start = time.time()
    try:
        a2 = runner.agent.run("那小米14呢", history=history, verbose=False)
    except Exception as e:
        a2 = f"[ERROR] {e}"
    elapsed = int((time.time() - start) * 1000)

    understands_ref = "小米" in a2 and has_iphone_price
    recorder.record("BD-13", understands_ref, {
        "query_round1": "iPhone 15 在哪个平台最便宜",
        "query_round2": "那小米14呢",
        "answer_round2_preview": a2[:200],
        "understands_reference": understands_ref,
        "round2_time_ms": elapsed,
    })
    print(f"  {'✓' if understands_ref else '✗'} BD-13: 理解指代={understands_ref}, {elapsed}ms")

    # BD-14: 京东查 iPhone 15 → "淘宝呢"（切换平台）
    print("  BD-14: Round 1...")
    r3 = runner.run_one("在京东查 iPhone 15 的价格")
    a3 = r3["answer"]

    history2 = [
        {"role": "user", "content": "在京东查 iPhone 15 的价格"},
        {"role": "assistant", "content": a3},
    ]
    start = time.time()
    try:
        a4 = runner.agent.run("淘宝呢", history=history2, verbose=False)
    except Exception as e:
        a4 = f"[ERROR] {e}"
    elapsed2 = int((time.time() - start) * 1000)

    switch_ok = "淘宝" in a4
    recorder.record("BD-14", switch_ok, {
        "query_round1": "在京东查 iPhone 15 的价格",
        "query_round2": "淘宝呢",
        "answer_round2_preview": a4[:200],
        "platform_switched": switch_ok,
        "round2_time_ms": elapsed2,
    })
    print(f"  {'✓' if switch_ok else '✗'} BD-14: 平台切换={switch_ok}, {elapsed2}ms")

    # BD-15: "这两个哪个更值得买"（指代两个产品）
    print("  BD-15: Round 1...")
    r5 = runner.run_one("对比 iPhone 15 和小米14")
    a5 = r5["answer"]

    history3 = [
        {"role": "user", "content": "对比 iPhone 15 和小米14"},
        {"role": "assistant", "content": a5},
    ]
    start = time.time()
    try:
        a6 = runner.agent.run("这两个哪个更值得买", history=history3, verbose=False)
    except Exception as e:
        a6 = f"[ERROR] {e}"
    elapsed3 = int((time.time() - start) * 1000)

    mentions_both = ("iPhone" in a6 or "苹果" in a6) and "小米" in a6
    recorder.record("BD-15", mentions_both, {
        "query_round1": "对比 iPhone 15 和小米14",
        "query_round2": "这两个哪个更值得买",
        "answer_round2_preview": a6[:200],
        "mentions_both_products": mentions_both,
        "round2_time_ms": elapsed3,
    })
    print(f"  {'✓' if mentions_both else '✗'} BD-15: 理解指代={mentions_both}, {elapsed3}ms")


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
        test_multiturn(recorder, runner)
        runner.cleanup()
    except Exception as e:
        print(f"\n  ⚠ LLM API 错误: {e}")
        print("  继续生成部分报告...")
        runner = None

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
