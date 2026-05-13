"""
P5 优化验证测试 — 验证坑2-5修复后的 Agent 行为
执行：python3 eval/eval_p5_optimization.py
约 13 个 case（含 LLM 调用），预计耗时 1-2 分钟

覆盖：
  P5-1: 自反思纠错（SR-01 ~ SR-04）
  P5-2: System Prompt 质量（SP-01 ~ SP-05）
  P5-3: 依赖注入 E2E（DI-E2E-01 ~ DI-E2E-02）
  P5-4: 复杂度判断 E2E（CD-E2E-01 ~ CD-E2E-02）
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_helpers import (
    EvalRecorder, save_report, print_summary,
    compute_all_prices, extract_prices, extract_platform_names,
    detect_hallucination
)

_time = time


class P5Runner:
    def __init__(self):
        from config import Settings
        from tools import tool_registry, init_parallel_agent, cleanup_parallel_agent
        from platforms import init_all_platforms
        from agent import ReActAgent

        init_all_platforms()
        init_parallel_agent()

        s = Settings()
        self.settings = s
        self.agent = ReActAgent(
            client=s.client,
            model=s.model,
            tools=tool_registry.get_schemas(),
            tool_map=tool_registry.get_tool_map(),
            max_round=s.max_round,
            config={
                "model_react": getattr(s, "model", "doubao-seed-2-0-pro-260215"),
                "model_plan": getattr(s, "model_plan", "doubao-seed-2-0-code-preview-260215"),
                "model_synthesize": getattr(s, "model_synthesize", "doubao-seed-2-0-pro-260215"),
                "max_plan_steps": getattr(s, "max_plan_steps", 8),
                "max_history_rounds": getattr(s, "max_history_rounds", 6),
                "max_history_chars": getattr(s, "max_history_chars", 6000),
                "complexity_keywords": getattr(s, "complexity_keywords", None),
                "complexity_patterns": getattr(s, "complexity_patterns", None),
                "max_reflection_retries": getattr(s, "max_reflection_retries", 2),
                "auto_relax_attributes": getattr(s, "auto_relax_attributes", True),
            },
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


# ── P5-1: 自反思纠错 ────────────────────────────────────────────────────────

def test_self_reflection(recorder: EvalRecorder, runner: P5Runner):
    """验证工具返回空时 Agent 的反思和追问行为"""
    print("\n--- P5-1: 自反思纠错 ---")

    # SR-01: 不存在商品 → 应优雅告知，不编造价格
    result = runner.run_one("华为Mate60 在哪个平台最便宜")
    answer = result["answer"]
    ground_truth = []  # 数据库中没有华为Mate60

    no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)
    not_found_keywords = ["未找到", "没有", "不存在", "无匹配", "未收录", "收录", "抱歉"]
    graceful = any(kw in answer for kw in not_found_keywords)

    passed = no_hallu and graceful
    recorder.record("SR-01", passed, {
        "query": "华为Mate60 在哪个平台最便宜",
        "answer_preview": answer[:200],
        "no_hallucination": no_hallu,
        "graceful_degradation": graceful,
        "hallucinations": hallu_prices,
    })
    print(f"  {'✓' if passed else '✗'} SR-01: hallucination={not no_hallu}, graceful={graceful}, {result['total_time_ms']}ms")
    _time.sleep(0.5)

    # SR-02: 不存在的属性组合 → 应尝试放宽条件或告知
    result = runner.run_one("iPhone 15 紫色 1TB 在哪买")
    answer = result["answer"]
    ground_truth = compute_all_prices("iPhone 15")

    no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)

    # 理想行为：告知无此配置，或回退到 iPhone 15 通用结果
    has_iphone = "iPhone" in answer
    no_bad_price = no_hallu

    passed = has_iphone and no_bad_price
    recorder.record("SR-02", passed, {
        "query": "iPhone 15 紫色 1TB 在哪买",
        "answer_preview": answer[:200],
        "mentions_iphone": has_iphone,
        "no_hallucination": no_hallu,
        "hallucinations": hallu_prices,
    })
    print(f"  {'✓' if passed else '✗'} SR-02: mentions_iphone={has_iphone}, halluc={not no_hallu}, {result['total_time_ms']}ms")
    _time.sleep(0.5)

    # SR-03: 不存在的品牌 → 应告知并列出可用商品
    result = runner.run_one("诺基亚3310 价格")
    answer = result["answer"]
    ground_truth = []

    no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)
    not_found = any(kw in answer for kw in ["未找到", "没有", "不存在", "无匹配", "数据库", "收录", "抱歉"])

    passed = no_hallu and not_found
    recorder.record("SR-03", passed, {
        "query": "诺基亚3310 价格",
        "answer_preview": answer[:200],
        "no_hallucination": no_hallu,
        "graceful_degradation": not_found,
        "hallucinations": hallu_prices,
    })
    print(f"  {'✓' if passed else '✗'} SR-03: halluc={not no_hallu}, graceful={not_found}, {result['total_time_ms']}ms")
    _time.sleep(0.5)

    # SR-04: 不存在商品 → 应尝试放宽属性（如去掉颜色/内存）后找到
    result = runner.run_one("小米14 金色 1TB 各平台价格")
    answer = result["answer"]
    ground_truth = compute_all_prices("小米14")

    has_xiaomi = "小米" in answer
    no_hallu, hallu_prices = detect_hallucination(answer, ground_truth)

    # 理想：放宽属性后找到了小米14
    passed = has_xiaomi and no_hallu
    recorder.record("SR-04", passed, {
        "query": "小米14 金色 1TB 各平台价格",
        "answer_preview": answer[:200],
        "mentions_xiaomi": has_xiaomi,
        "no_hallucination": no_hallu,
        "hallucinations": hallu_prices,
        "prices_found": result["prices"],
    })
    print(f"  {'✓' if passed else '✗'} SR-04: mentions_xiaomi={has_xiaomi}, prices={result['prices'][:3]}, {result['total_time_ms']}ms")
    _time.sleep(0.5)


# ── P5-2: System Prompt 质量 ─────────────────────────────────────────────────

def test_system_prompt_quality(recorder: EvalRecorder, runner: P5Runner):
    """验证 System Prompt 引导下的输出质量和追问行为"""
    print("\n--- P5-2: System Prompt 质量 ---")

    # SP-01: 比价查询 → 答案必须包含平台名和价格
    result = runner.run_one("iPhone 15 在哪个平台最便宜")
    answer = result["answer"]

    has_platform = len(result["platforms"]) > 0
    has_price = len(result["prices"]) > 0
    passed = has_platform and has_price

    recorder.record("SP-01", passed, {
        "query": "iPhone 15 在哪个平台最便宜",
        "answer_preview": answer[:200],
        "platforms_mentioned": result["platforms"],
        "prices_mentioned": result["prices"][:5],
        "has_platform": has_platform,
        "has_price": has_price,
    })
    print(f"  {'✓' if passed else '✗'} SP-01: platforms={result['platforms']}, prices={len(result['prices'])}, {result['total_time_ms']}ms")
    _time.sleep(0.5)

    # SP-02: 单品查询 → 答案必须标注来源平台
    result = runner.run_one("小米14 黑色 256GB 价格")
    answer = result["answer"]

    has_platform = len(result["platforms"]) > 0
    has_price = len(result["prices"]) > 0
    passed = has_platform and has_price

    recorder.record("SP-02", passed, {
        "query": "小米14 黑色 256GB 价格",
        "answer_preview": answer[:200],
        "platforms_mentioned": result["platforms"],
        "has_platform": has_platform,
        "has_price": has_price,
    })
    print(f"  {'✓' if passed else '✗'} SP-02: platforms={result['platforms']}, prices={len(result['prices'])}, {result['total_time_ms']}ms")
    _time.sleep(0.5)

    # SP-03: "苹果"歧义输入 → 应反问澄清
    result = runner.run_one("苹果")
    answer = result["answer"]

    clarification_keywords = ["请问", "您是指", "具体", "哪一款", "什么产品", "iPhone", "iPad", "AirPods"]
    asks_clarify = any(kw in answer for kw in clarification_keywords)

    recorder.record("SP-03", asks_clarify, {
        "query": "苹果",
        "answer_preview": answer[:200],
        "asks_clarification": asks_clarify,
    })
    print(f"  {'✓' if asks_clarify else '✗'} SP-03: asks_clarify={asks_clarify}, {result['total_time_ms']}ms")
    _time.sleep(0.5)

    # SP-04: "15" 极简输入 → 应反问
    result = runner.run_one("15")
    answer = result["answer"]

    clarification_keywords = ["请问", "您是指", "具体", "iPhone", "型号", "什么", "哪一款"]
    asks_clarify = any(kw in answer for kw in clarification_keywords)

    recorder.record("SP-04", asks_clarify, {
        "query": "15",
        "answer_preview": answer[:200],
        "asks_clarification": asks_clarify,
    })
    print(f"  {'✓' if asks_clarify else '✗'} SP-04: asks_clarify={asks_clarify}, {result['total_time_ms']}ms")
    _time.sleep(0.5)

    # SP-05: 空输入 → 应引导用户
    result = runner.run_one("")
    answer = result["answer"]

    guide_keywords = ["您好", "请问", "查询", "输入", "商品", "可以", "帮您"]
    guides_user = any(kw in answer for kw in guide_keywords) and len(answer) > 10

    recorder.record("SP-05", guides_user, {
        "query": "(empty)",
        "answer_preview": answer[:200],
        "guides_user": guides_user,
    })
    print(f"  {'✓' if guides_user else '✗'} SP-05: guides_user={guides_user}, answer_len={len(answer)}, {result['total_time_ms']}ms")
    _time.sleep(0.5)


# ── P5-3: 依赖注入 E2E ──────────────────────────────────────────────────────

def test_dependency_injection_e2e(recorder: EvalRecorder, runner: P5Runner):
    """验证 Plan-Execute 中依赖引用能否正确解析"""
    print("\n--- P5-3: 依赖注入 E2E ---")

    # DI-E2E-01: "iPhone 15 最便宜的平台是哪个，在那个平台也查一下小米14"
    # 期望：Plan 有 2 步，Step 2 的 platform_id 引用 Step 1 的结果
    result = runner.run_one("iPhone 15 在哪个平台最便宜，在那个平台也查一下小米14")
    answer = result["answer"]

    has_iphone = "iPhone" in answer or "苹果" in answer.lower()
    has_xiaomi = "小米" in answer
    passed = has_iphone and has_xiaomi

    recorder.record("DI-E2E-01", passed, {
        "query": "iPhone 15 在哪个平台最便宜，在那个平台也查一下小米14",
        "answer_preview": answer[:250],
        "mentions_iphone": has_iphone,
        "mentions_xiaomi": has_xiaomi,
    })
    print(f"  {'✓' if passed else '✗'} DI-E2E-01: iphone={has_iphone}, xiaomi={has_xiaomi}, {result['total_time_ms']}ms")
    _time.sleep(0.5)

    # DI-E2E-02: "先对比 iPhone 15 在各平台价格，再用最低价平台的接口查 AirPods Pro 2"
    result = runner.run_one("先对比 iPhone 15 的价格，再在最便宜的平台查 AirPods Pro 2")
    answer = result["answer"]

    has_iphone = "iPhone" in answer or "苹果" in answer.lower()
    has_airpods = "AirPods" in answer or "耳机" in answer
    passed = has_iphone and has_airpods

    recorder.record("DI-E2E-02", passed, {
        "query": "先对比 iPhone 15 的价格，再在最便宜的平台查 AirPods Pro 2",
        "answer_preview": answer[:250],
        "mentions_iphone": has_iphone,
        "mentions_airpods": has_airpods,
    })
    print(f"  {'✓' if passed else '✗'} DI-E2E-02: iphone={has_iphone}, airpods={has_airpods}, {result['total_time_ms']}ms")
    _time.sleep(0.5)


# ── P5-4: 复杂度判断 E2E ──────────────────────────────────────────────────────

def test_complexity_e2e(recorder: EvalRecorder, runner: P5Runner):
    """验证复杂 query 是否正确路由到 Plan-Execute"""
    print("\n--- P5-4: 复杂度判断 E2E ---")

    # CD-E2E-01: 简单 query → 应走 ReAct 路径（快，1-2 轮）
    result = runner.run_one("小米14 价格")
    answer = result["answer"]
    has_price = len(result["prices"]) > 0

    recorder.record("CD-E2E-01", has_price, {
        "query": "小米14 价格",
        "answer_preview": answer[:150],
        "has_price": has_price,
        "total_time_ms": result["total_time_ms"],
    })
    print(f"  {'✓' if has_price else '✗'} CD-E2E-01: has_price={has_price}, {result['total_time_ms']}ms")
    _time.sleep(0.5)

    # CD-E2E-02: 复杂 query → 应走 Plan-Execute (有独立分析)
    result = runner.run_one("对比 iPhone 15 和小米14，分析哪个性价比更高")
    answer = result["answer"]

    has_iphone = "iPhone" in answer or "苹果" in answer.lower()
    has_xiaomi = "小米" in answer
    has_comparison = any(kw in answer for kw in ["对比", "比较", "差异", "优势", "性价比", "推荐", "相差"])

    passed = has_iphone and has_xiaomi and has_comparison
    recorder.record("CD-E2E-02", passed, {
        "query": "对比 iPhone 15 和小米14，分析哪个性价比更高",
        "answer_preview": answer[:200],
        "mentions_iphone": has_iphone,
        "mentions_xiaomi": has_xiaomi,
        "has_comparison": has_comparison,
    })
    print(f"  {'✓' if passed else '✗'} CD-E2E-02: iphone={has_iphone}, xiaomi={has_xiaomi}, compare={has_comparison}, {result['total_time_ms']}ms")


def main():
    print("=" * 60)
    print("  P5 优化验证测试（自反思 + Prompt + 依赖注入 + 复杂度）")
    print("=" * 60)

    recorder = EvalRecorder("P5_optimization")
    runner = P5Runner()

    try:
        # P5-1: 自反思纠错 (4 cases)
        test_self_reflection(recorder, runner)

        # P5-2: System Prompt 质量 (5 cases)
        test_system_prompt_quality(recorder, runner)

        # P5-3: 依赖注入 E2E (2 cases)
        test_dependency_injection_e2e(recorder, runner)

        # P5-4: 复杂度判断 E2E (2 cases)
        test_complexity_e2e(recorder, runner)

    finally:
        runner.cleanup()

    summary = recorder.summary()
    print_summary(summary)

    filename = save_report("P5_optimization", summary)
    print(f"报告已保存: {filename}")

    return summary["failed"] == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
