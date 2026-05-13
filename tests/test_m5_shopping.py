"""
测试 M5 引导式购物 Agent — 意图分类、ShoppingContext 状态机、槽位提取、对话流程、回归。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_shopping_context():
    """ShoppingContext 状态机基本操作"""
    print("[1/6] ShoppingContext 单元...")
    from agent.react_engine import ShoppingContext

    ctx = ShoppingContext()
    assert ctx.phase == "greeting"
    assert ctx.question_count == 0
    assert ctx.slots == {}
    assert ctx.candidates == []
    assert ctx.compare_basket == []

    # add_slot + get_missing_required
    ctx.add_slot("primary_use_case", "gaming")
    assert ctx.slots["primary_use_case"] == "gaming"

    slot_defs = [
        {"name": "primary_use_case", "required": True},
        {"name": "budget_range", "required": False},
    ]
    missing = ctx.get_missing_required(slot_defs)
    assert len(missing) == 0, f"primary_use_case 已填，不应缺失: {missing}"

    ctx.add_slot("budget_range", 5000)
    missing = ctx.get_missing_required(slot_defs)
    assert len(missing) == 0

    # reset
    ctx.reset()
    assert ctx.phase == "greeting"
    assert len(ctx.slots) == 0
    assert ctx.question_count == 0
    assert ctx.last_recommendation is None

    print(f"  ✓ 状态机基本操作正确（add/get_missing/reset）")


def test_intent_detection():
    """_detect_intent shopping 分类"""
    print("[2/6] 意图分类...")
    from config import Settings
    from tools import tool_registry, init_parallel_agent
    from platforms import init_all_platforms
    from agent import ReActAgent

    init_all_platforms()
    init_parallel_agent()
    s = Settings()
    agent = ReActAgent(
        client=s.client, model=s.model,
        tools=tool_registry.get_schemas(),
        tool_map=tool_registry.get_tool_map(),
        config={"industry_config": s.industry_config},
    )

    cases = [
        # (query, expected_intent)
        ("想买个手机", "shopping"),
        ("帮我挑一款", "shopping"),
        ("想换个手机", "shopping"),
        ("买个", "shopping"),
        # 不触发 shopping 的情况
        ("iPhone 15 多少钱", "query"),
        ("推荐游戏手机", "recommendation"),
        ("5000以内拍照好的", "recommendation"),
        ("iPhone 15 和小米14 哪个好", "comparison"),
        ("想买个游戏手机", "recommendation"),   # 有场景词 → recommendation
        ("想买5000左右的", "recommendation"),   # 有预算 → recommendation
    ]

    all_ok = True
    for query, expected in cases:
        result = agent._detect_intent(query)
        if result != expected:
            print(f"  ✗ '{query}' → {result} (期望 {expected})")
            all_ok = False

    if all_ok:
        print(f"  ✓ {len(cases)} 个 case 全部正确")

    return agent


def test_slot_extraction(agent):
    """槽位提取"""
    print("[3/6] 槽位提取...")
    ctx = agent.shopping_context
    ctx.reset()
    slots_cfg = agent.industry_config.get("shopping_slots", [])

    # 提取 use_case
    ctx.reset()
    agent._extract_slots_from_query("主要是打游戏用", slots_cfg)
    assert ctx.slots.get("primary_use_case") == "gaming", \
        f"应提取 gaming: {ctx.slots}"

    # 提取预算
    ctx.reset()
    agent._extract_slots_from_query("拍照好预算5000以内", slots_cfg)
    assert ctx.slots.get("primary_use_case") == "photography", \
        f"应提取 photography: {ctx.slots}"
    assert ctx.slots.get("budget_max") == 5000, \
        f"应提取 budget_max=5000: {ctx.slots}"

    # 提取品牌
    ctx.reset()
    agent._extract_slots_from_query("想买个小米的手机", slots_cfg)
    assert ctx.slots.get("brand_preference") == "小米", \
        f"应提取 brand_preference=小米: {ctx.slots}"

    # 提取处理器
    ctx.reset()
    agent._extract_slots_from_query("骁龙处理器的", slots_cfg)
    assert ctx.slots.get("processor_preference") == "骁龙", \
        f"应提取 processor_preference=骁龙: {ctx.slots}"

    print(f"  ✓ use_case/budget/brand/processor 提取正确")


def test_guided_shopping_flow(agent):
    """3 轮购物对话流程"""
    print("[4/6] 购物对话流程...")
    ctx = agent.shopping_context
    ctx.reset()

    # 轮1: 模糊需求 → 应追问使用场景
    r1 = agent._guided_shopping("想买个手机", None, True)
    assert "打游戏" in r1 or "拍照" in r1 or "日常" in r1, \
        f"应追问使用场景: {r1[:80]}"
    assert ctx.phase in ("slot_filling", "searching"), \
        f"phase 应为 slot_filling 或 searching: {ctx.phase}"

    # 轮2: 补充场景 → 必填槽位满足 → 搜索推荐
    r2 = agent._guided_shopping("打游戏", None, True)
    assert ctx.slots.get("primary_use_case") == "gaming", \
        f"应有 gaming slot: {ctx.slots}"
    assert "为您找到" in r2 or "¥" in r2 or "共找到" in r2, \
        f"应给出推荐: {r2[:80]}"

    # 轮3: 追加预算 → 重新搜索
    r3 = agent._guided_shopping("5000以内", None, True)
    assert ctx.slots.get("budget_max") == 5000, \
        f"应有 budget_max=5000: {ctx.slots}"
    assert "¥" in r3, f"应包含价格信息: {r3[:80]}"

    print(f"  ✓ 3 轮对话: 追问场景 → 搜索推荐 → 预算筛选")


def test_followup_and_comparison(agent):
    """跟进处理和对比模式"""
    print("[5/6] FOLLOW_UP + COMPARING...")
    ctx = agent.shopping_context

    # 设置状态：正在推荐中，有候选商品
    ctx.reset()
    ctx.phase = "recommending"
    ctx.candidates = [
        {"product_name": "小米14", "price": 3999, "platform": "京东",
         "processor": "骁龙8Gen3", "performance_tier": "flagship",
         "battery": 4610, "screen_size": 6.36},
        {"product_name": "iPhone 15 Pro", "price": 8999, "platform": "京东",
         "processor": "A17 Pro", "performance_tier": "flagship",
         "battery": 3274, "screen_size": 6.1},
    ]
    ctx.last_recommendation = {"recommendations": ctx.candidates, "total_found": 2}

    # 测试对比意图触发
    r = agent._handle_followup("这两个哪个好")
    assert ctx.phase == "comparing" or ctx.phase == "follow_up", \
        f"对比后 phase 应为 comparing 或 follow_up: {ctx.phase}"

    # 测试结束
    r_end = agent._handle_followup("谢谢，就这个")
    assert ctx.phase == "greeting", f"结束后 phase 应为 greeting: {ctx.phase}"

    print(f"  ✓ 对比触发 + 退出重置正确")


def test_regression():
    """已有功能不受影响"""
    print("[6/6] 已有功能回归...")
    import sys, os
    sys.path.insert(0, "eval")

    import eval_helpers
    from eval_it3c import test_intent_detection, test_semantic_search_filters
    from eval_p0_unit import test_scoring, test_parallel

    r = eval_helpers.EvalRecorder("M5-script-regression")
    test_intent_detection(r)
    test_semantic_search_filters(r)
    test_scoring(r)
    test_parallel(r)
    s = r.summary()
    assert s["failed"] == 0, f"回归失败: {s['failed']} 项"
    print(f"  ✓ {s['passed']}/{s['total']} 回归通过")


def main():
    print("=" * 56)
    print("  M5 引导式购物 Agent — 验证测试")
    print("=" * 56)

    test_shopping_context()
    agent = test_intent_detection()
    test_slot_extraction(agent)
    test_guided_shopping_flow(agent)
    test_followup_and_comparison(agent)
    test_regression()

    print(f"\n{'=' * 56}")
    print("  M5 全部通过")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    main()
