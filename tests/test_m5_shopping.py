"""
测试 M5 引导式购物 Agent — 意图分类、ShoppingContext 状态机、槽位提取、对话流程、回归。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_shopping_context():
    """ShoppingContext 状态机基本操作"""
    print("[1/9] ShoppingContext 单元...")
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
    print("[2/9] 意图分类...")
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
    print("[3/9] 槽位提取...")
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
    print("[4/9] 购物对话流程...")
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
    print("[5/9] FOLLOW_UP + COMPARING...")
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
    print("[6/9] 已有功能回归...")
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


def test_topic_switch_and_ending(agent):
    """_is_topic_switch 和 _is_ending_shopping 边界条件"""
    print("[7/9] 话题切换与结束检测...")
    ctx = agent.shopping_context
    ctx.reset()

    # ── _is_ending_shopping ──

    # 纯结束 — "算了"/"不买了"/"不用了谢谢"
    assert agent._is_ending_shopping("算了") is True
    assert agent._is_ending_shopping("不买了") is True
    assert agent._is_ending_shopping("好的谢谢") is True
    assert agent._is_ending_shopping("就这个，下单吧") is True

    # 结束词 + 新查询意图 → 不算结束（让给 _is_topic_switch）
    assert agent._is_ending_shopping("算了帮我查iPhone 15") is False, \
        "结束词+具体型号 → 不应判为结束"
    assert agent._is_ending_shopping("不用了搜一下小米14") is False, \
        "结束词+搜一下 → 不应判为结束"

    # 不是结束词
    assert agent._is_ending_shopping("打游戏") is False
    assert agent._is_ending_shopping("预算4000") is False

    # ── _is_topic_switch ──

    # 未提具体型号 → 不切换
    assert agent._is_topic_switch("打游戏") is False
    assert agent._is_topic_switch("预算4000以内") is False
    assert agent._is_topic_switch("便宜点的") is False

    # 提到具体型号 → 切换
    assert agent._is_topic_switch("帮我查iPhone 15") is True
    assert agent._is_topic_switch("小米14怎么样") is True

    # 提到具体型号但该型号在当前候选列表 → 不切换（在对比推荐商品）
    ctx.candidates = [
        {"product_name": "小米14", "price": 3999},
        {"product_name": "iPhone 15 Pro", "price": 8999},
    ]
    assert agent._is_topic_switch("小米14怎么样") is False, \
        "候选商品在列表内 → 不算切换"
    assert agent._is_topic_switch("帮我查iPad Pro") is True, \
        "iPad Pro 不在候选 → 应算切换"

    ctx.reset()
    print(f"  ✓ _is_topic_switch / _is_ending_shopping 边界正确")


def test_slot_filling_irrelevant_input(agent):
    """SLOT_FILLING 阶段前言不搭后语 → 不计入 question_count"""
    print("[8/9] 槽位填充 — 无关输入处理...")
    ctx = agent.shopping_context
    ctx.reset()

    # Round 1: 启动购物 → GREETING → 追问使用场景
    r1 = agent._guided_shopping("想买个手机", None, True)
    assert ctx.phase == "slot_filling", f"phase={ctx.phase}"
    assert ctx.question_count == 0, f"question_count={ctx.question_count}"

    # 记下追问的内容
    assert "打游戏" in r1 or "拍照" in r1, f"应追问场景: {r1[:80]}"

    # Round 2: 无关输入 → 不计入次数，重新追问
    r2 = agent._guided_shopping("今天天气不错", None, True)
    assert ctx.question_count == 0, \
        f"无关输入不应计数，question_count={ctx.question_count}"
    assert ctx.phase == "slot_filling", \
        f"无关输入不应改变 phase: {ctx.phase}"
    assert "打游戏" in r2 or "拍照" in r2, \
        f"应重新追问: {r2[:80]}"

    # Round 3: 继续无关输入 → 仍不计入
    r3 = agent._guided_shopping("你好啊", None, True)
    assert ctx.question_count == 0, \
        f"连续无关输入不应计数: {ctx.question_count}"

    # Round 4: 有效输入 → 正常计数并推进
    r4 = agent._guided_shopping("打游戏", None, True)
    assert ctx.question_count == 1, \
        f"有效输入后 question_count={ctx.question_count} (应=1)"
    assert ctx.slots.get("primary_use_case") == "gaming", \
        f"应提取 gaming slot: {ctx.slots}"

    ctx.reset()
    print(f"  ✓ 无关输入不消耗追问次数，有效输入正常推进")


def test_run_routing_persistence(agent):
    """run() 购物激活后路由到 _guided_shopping 而非意图分类"""
    print("[9/9] run() 购物路由持久性...")
    ctx = agent.shopping_context

    # ── 场景 1: 购物激活 → 话题切换退出 ──
    ctx.reset()
    # 先启动购物模式
    r1 = agent.run("想买个手机", verbose=False)
    assert ctx.phase != "greeting", f"购物应已激活: phase={ctx.phase}"

    # 提到具体型号 → 检测话题切换 → reset → 走 normal routing (query)
    r2 = agent.run("帮我查iPhone 15 价格", verbose=False)
    assert ctx.phase == "greeting", \
        f"话题切换后 ctx 应 reset: phase={ctx.phase}"

    # ── 场景 2: 购物激活 → 槽位回复不被误判 ──
    ctx.reset()
    # 购物模式启动 — 只需 GREETING 就能断言 (无 LLM)
    r1 = agent.run("想买个手机", verbose=False)
    assert ctx.phase in ("slot_filling", "searching"), \
        f"购物启动后 phase={ctx.phase}"

    # "打游戏" 在修复前会被 _detect_intent 判为 recommendation
    # 修复后应直接进入 _guided_shopping → SLOT_FILLING
    r2 = agent.run("打游戏的", verbose=False)
    # 如果被误判为 recommendation，不会提取 gaming slot
    # 如果正确路由到 shopping，ctx 中应有 gaming
    assert ctx.slots.get("primary_use_case") == "gaming", \
        f"槽位应被提取: slots={ctx.slots}"

    # ── 场景 3: 购物激活 → 结束退出 ──
    ctx.reset()
    agent.run("想换个手机", verbose=False)
    assert ctx.phase != "greeting", f"购物应已激活: phase={ctx.phase}"

    r3 = agent.run("不用了谢谢", verbose=False)
    assert ctx.phase == "greeting", f"结束应 reset: phase={ctx.phase}"
    assert "好" in r3, f"应有告别语: {r3[:50]}"

    ctx.reset()
    print(f"  ✓ 购物路由持久: 续/切换/退出 均正确")


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

    # ── 新增: 路由修复验证 ──
    test_topic_switch_and_ending(agent)
    test_slot_filling_irrelevant_input(agent)
    test_run_routing_persistence(agent)

    print(f"\n{'=' * 56}")
    print("  M5 全部通过")
    print(f"{'=' * 56}")


if __name__ == "__main__":
    main()
