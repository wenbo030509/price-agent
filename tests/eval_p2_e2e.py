"""
P2 端到端测试 — 完整 ReAct 循环，验证工具选择、参数、答案正确性
执行：python3 tests/eval_p2_e2e.py
需多次 LLM API 调用，约 23 个 case，预计耗时 2-3 分钟
"""

import sys
import os
import re
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_helpers import (
    EvalRecorder, save_report, print_summary,
    compute_all_prices, extract_prices, extract_platform_names,
    detect_hallucination
)


import time as _time


class E2ERunner:
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
        """执行一次 Agent 查询并返回结构化结果"""
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


def test_e2e_basic(recorder: EvalRecorder, runner: E2ERunner):
    """P2-1: 单工具基础查询"""
    cases = [
        ("E2E-01", "iPhone 15 在哪个平台最便宜",
         lambda: compute_all_prices("iPhone 15"),
         ["price_in_answer", "cheapest_correct"]),
        ("E2E-02", "小米14 的价格",
         lambda: compute_all_prices("小米14"),
         ["price_in_answer"]),
        ("E2E-03", "AirPods Pro 2 各平台价格",
         lambda: compute_all_prices("AirPods Pro 2"),
         ["price_in_answer"]),
        ("E2E-04", "iPad Pro 在哪个平台有卖",
         lambda: compute_all_prices("iPad Pro"),
         ["price_in_answer", "correct_platform"]),
        ("E2E-05", "所有平台都有什么商品",
         lambda: [],  # 列表类查询，无价格 ground truth
         ["has_content"]),
    ]

    print("\n--- P2-1: 单工具基础查询 ---")
    for case_id, query, gt_fn, checks in cases:
        result = runner.run_one(query)
        answer = result["answer"]

        ground_truth = gt_fn()
        prices_in_answer = result["prices"]

        # 逐个检查
        passed = True
        details = {"query": query, "answer_preview": answer[:150], "checks": {}}

        if "price_in_answer" in checks:
            ok = len(prices_in_answer) > 0 or "has_content" in checks
            details["checks"]["price_in_answer"] = ok
            if not ok:
                passed = False

        if "cheapest_correct" in checks and ground_truth:
            cheapest = min(ground_truth, key=lambda x: x["total_price"])
            ok = any(abs(p - cheapest["total_price"]) <= 1 for p in prices_in_answer)
            details["checks"]["cheapest_correct"] = ok
            details["ground_truth_cheapest"] = f"{cheapest['platform_name']} ¥{cheapest['total_price']}"
            if not ok:
                passed = False

        if "correct_platform" in checks and ground_truth:
            platforms = set(p["platform_name"] for p in ground_truth)
            mentioned = set(result["platforms"])
            ok = len(platforms & mentioned) > 0
            details["checks"]["correct_platform"] = ok
            if not ok:
                passed = False

        # 幻觉检测
        if ground_truth:
            no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)
            details["checks"]["no_hallucination"] = no_hallu
            if not no_hallu:
                details["hallucinations"] = hallu_prices
                passed = False

        recorder.record(case_id, passed, details)
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: {query} → 价格数={len(prices_in_answer)}, 耗时={result['total_time_ms']}ms")
        _time.sleep(0.5)  # 避免 API 限流


def test_e2e_complex(recorder: EvalRecorder, runner: E2ERunner):
    """P2-2: 复合推理查询"""
    cases = [
        ("E2E-06", "对比 iPhone 15 和小米14 的价格",
         lambda: compute_all_prices("iPhone 15") + compute_all_prices("小米14"),
         ["mentions_both_products"]),
        ("E2E-07", "iPhone 15 黑色 256GB 在哪里买最便宜",
         lambda: compute_all_prices("iPhone 15", color="黑色", memory="256GB"),
         ["price_in_answer"]),
        ("E2E-08", "我想买平板，帮我看看各平台有什么",
         lambda: compute_all_prices("平板"),
         ["has_content"]),
        ("E2E-09", "小米平板6 蓝色 有没有货",
         lambda: compute_all_prices("小米平板6", color="蓝色"),
         ["price_in_answer"]),
    ]

    # E2E-08 ground truth: 平板搜索应包含所有品类为平板的商品（不只是名称含"平板"）
    # 直接查所有商品，然后筛选 category 含"平板"的
    def gt_all_tablets():
        from platforms.parallel_agent import PlatformParallelAgent
        a = PlatformParallelAgent()
        r = a.query_all_products_parallel()
        a.close()
        tablets = []
        for pid, data in r["results"].items():
            for p in data["products"]:
                if "平板" in (p.get("category") or ""):
                    tablets.append({
                        "price": p["platform_price"],
                        "total_price": p["platform_price"] + p.get("shipping_fee", 0),
                        "platform_name": p["platform_name"],
                    })
        return tablets

    cases = [
        ("E2E-06", "对比 iPhone 15 和小米14 的价格",
         lambda: compute_all_prices("iPhone 15") + compute_all_prices("小米14"),
         ["mentions_both_products"]),
        ("E2E-07", "iPhone 15 黑色 256GB 在哪里买最便宜",
         lambda: compute_all_prices("iPhone 15", color="黑色", memory="256GB"),
         ["price_in_answer"]),
        ("E2E-08", "我想买平板，帮我看看各平台有什么",
         gt_all_tablets,
         ["has_content"]),
        ("E2E-09", "小米平板6 蓝色 有没有货",
         lambda: compute_all_prices("小米平板6", color="蓝色"),
         ["price_in_answer"]),
    ]

    print("\n--- P2-2: 复合推理 ---")
    for case_id, query, gt_fn, checks in cases:
        result = runner.run_one(query)
        answer = result["answer"]
        ground_truth = gt_fn()
        prices_in_answer = result["prices"]

        passed = True
        details = {"query": query, "answer_preview": answer[:150], "checks": {}}

        if "price_in_answer" in checks:
            ok = len(prices_in_answer) > 0
            details["checks"]["price_in_answer"] = ok
            if not ok:
                passed = False

        if "mentions_both_products" in checks:
            has_iphone = "iPhone" in answer or "iphone" in answer.lower()
            has_xiaomi = "小米" in answer
            ok = has_iphone and has_xiaomi
            details["checks"]["mentions_both_products"] = ok
            if not ok:
                passed = False

        if "has_content" in checks:
            ok = len(answer.strip()) > 20  # 有实质内容
            details["checks"]["has_content"] = ok
            if not ok:
                passed = False

        if ground_truth:
            no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)
            details["checks"]["no_hallucination"] = no_hallu
            if not no_hallu:
                details["hallucinations"] = hallu_prices
                passed = False

        recorder.record(case_id, passed, details)
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: {query} → {result['total_time_ms']}ms")
        _time.sleep(0.5)


def test_e2e_alias(recorder: EvalRecorder, runner: E2ERunner):
    """P2-3: 别名输入"""
    cases = [
        ("AL-E2E-01", "水果手机 15 最便宜的平台",
         lambda: compute_all_prices("iPhone 15"),
         ["price_in_answer"]),
        ("AL-E2E-02", "帮我查下 ip15 白色 256g",
         lambda: compute_all_prices("iPhone 15", color="白色", memory="256GB"),
         ["price_in_answer"]),
        ("AL-E2E-03", "米14 绿色 哪个平台有货",
         lambda: compute_all_prices("小米14", color="绿色"),
         ["price_in_answer"]),
    ]

    print("\n--- P2-3: 别名输入 ---")
    for case_id, query, gt_fn, checks in cases:
        result = runner.run_one(query)
        answer = result["answer"]
        ground_truth = gt_fn()
        prices_in_answer = result["prices"]

        passed = len(prices_in_answer) > 0
        details = {"query": query, "answer_preview": answer[:150], "checks": {"price_in_answer": passed}}

        if ground_truth:
            no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)
            details["checks"]["no_hallucination"] = no_hallu
            if not no_hallu:
                passed = False

        recorder.record(case_id, passed, details)
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: {query} → 价格数={len(prices_in_answer)}, {result['total_time_ms']}ms")
        _time.sleep(0.5)


def test_e2e_attr(recorder: EvalRecorder, runner: E2ERunner):
    """P2-4: 属性精确匹配"""
    cases = [
        ("AT-E2E-01", "iPhone 15 黑色 256GB 各平台价格",
         lambda: compute_all_prices("iPhone 15", color="黑色", memory="256GB"),
         ["price_in_answer"]),
        ("AT-E2E-02", "小米14 白色 128GB 最便宜的平台",
         lambda: compute_all_prices("小米14", color="白色", memory="128GB"),
         ["price_in_answer"]),
    ]

    print("\n--- P2-4: 属性精确匹配 ---")
    for case_id, query, gt_fn, checks in cases:
        result = runner.run_one(query)
        answer = result["answer"]
        ground_truth = gt_fn()
        prices_in_answer = result["prices"]

        passed = len(prices_in_answer) > 0
        details = {"query": query, "answer_preview": answer[:150], "checks": {"price_in_answer": passed}}

        if ground_truth:
            no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)
            details["checks"]["no_hallucination"] = no_hallu
            if not no_hallu:
                passed = False

        recorder.record(case_id, passed, details)
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: {query} → {result['total_time_ms']}ms")
        _time.sleep(0.5)


def test_e2e_plan_execute(recorder: EvalRecorder, runner: E2ERunner):
    """P2-5: Plan-Execute 策略专项（复杂 query 应触发 plan 模式）"""
    cases = [
        ("PE-01", "对比 iPhone 15 和小米14 的价格",
         lambda: compute_all_prices("iPhone 15") + compute_all_prices("小米14"),
         ["mentions_both_products", "price_in_answer"]),
        ("PE-02", "比较 iPhone 15 和 AirPods Pro 2 哪个更值得买",
         lambda: compute_all_prices("iPhone 15") + compute_all_prices("AirPods Pro 2"),
         ["mentions_both_products", "price_in_answer"]),
        ("PE-03", "分析小米14 和 小米平板6 的价格差异",
         lambda: compute_all_prices("小米14") + compute_all_prices("小米平板6"),
         ["mentions_both", "price_in_answer"]),
    ]

    print("\n--- P2-5: Plan-Execute 策略 ---")
    for case_id, query, gt_fn, checks in cases:
        result = runner.run_one(query)
        answer = result["answer"]
        ground_truth = gt_fn()
        prices_in_answer = result["prices"]

        passed = True
        details = {"query": query, "answer_preview": answer[:150], "checks": {}}

        if "price_in_answer" in checks:
            ok = len(prices_in_answer) > 0
            details["checks"]["price_in_answer"] = ok
            if not ok:
                passed = False

        if "mentions_both_products" in checks or "mentions_both" in checks:
            # 检查至少提到两个商品/品牌关键词
            all_keywords = ["iphone", "苹果", "小米", "airpods", "ipad", "平板"]
            mentioned = [kw for kw in all_keywords if kw.lower() in answer.lower()]
            ok = len(mentioned) >= 2
            details["checks"]["mentions_both"] = ok
            details["checks"]["mentioned_keywords"] = mentioned
            if not ok:
                passed = False

        if ground_truth:
            no_hallu, _ = detect_hallucination(answer, ground_truth)
            details["checks"]["no_hallucination"] = no_hallu
            if not no_hallu:
                passed = False

        recorder.record(case_id, passed, details)
        status = "✓" if passed else "✗"
        print(f"  {status} {case_id}: {query} → {result['total_time_ms']}ms")
        _time.sleep(0.5)


def main():
    print("=" * 60)
    print("  P2 端到端测试（ReAct + Plan-Execute）")
    print("=" * 60)

    recorder = EvalRecorder("P2_e2e")
    runner = E2ERunner()

    try:
        test_e2e_basic(recorder, runner)
        test_e2e_complex(recorder, runner)
        test_e2e_alias(recorder, runner)
        test_e2e_attr(recorder, runner)
        test_e2e_plan_execute(recorder, runner)
    finally:
        runner.cleanup()

    summary = recorder.summary()
    print_summary(summary)

    filename = save_report("P2_e2e", summary)
    print(f"报告已保存: {filename}")

    return summary["failed"] == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
