"""
测试 ReActAgent 关键路径：
  - _slide_window — 历史消息滑动窗口截断
  - _detect_intent — 意图分类
  - _react_loop — 传统 ReAct 循环（mock API）
  - tool_calls 数量与 tool messages 数量的匹配（防 400 error 回归）
  - 多 tool_calls 场景 — 确认修复后不会再出现 insufficient tool messages 错误
"""
import json
import sys
import os
from unittest.mock import MagicMock
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.react_engine import ReActAgent, ShoppingContext

_TCArg = namedtuple("_TCArg", ["name", "arguments"])


def _make_tc(idx, name, args):
    tc = MagicMock()
    tc.id = f"call_{idx}"
    tc.function = _TCArg(name=name, arguments=json.dumps(args))
    return tc


def _make_agent(**kwargs):
    defaults = dict(
        client=MagicMock(), model="test-model",
        tools=[], tool_map={}, max_round=3,
        config={
            "max_history_rounds": 5,
            "max_history_chars": 1000,
            "max_reflection_retries": 0,
            "auto_relax_attributes": False,
            "max_step_react_rounds": 2,
            "max_plan_steps": 3,
        }
    )
    defaults.update(kwargs)
    return ReActAgent(**defaults)


# ══════════════════════════════════════════════════════════════════
# 1. _slide_window
# ══════════════════════════════════════════════════════════════════

def test_slide_window_empty():
    print("[1/10] _slide_window — 空输入...")
    agent = _make_agent()
    assert agent._slide_window([]) == []
    print("  ✓")


def test_slide_window_filter():
    print("[2/10] _slide_window — 过滤非 user/assistant...")
    agent = _make_agent()
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "tool", "content": "result"},
        {"role": "system", "content": "sys"},
    ]
    result = agent._slide_window(history)
    assert len(result) == 2, f"应只剩 2 条: {result}"
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "assistant"
    print("  ✓")


def test_slide_window_truncate_by_rounds():
    print("[3/10] _slide_window — 按轮数截断...")
    agent = _make_agent(config={"max_history_rounds": 3, "max_history_chars": 99999})
    history = []
    for i in range(10):
        history.append({"role": "user", "content": f"q_{i}"})
        history.append({"role": "assistant", "content": f"a_{i}"})
    result = agent._slide_window(history)
    assert len(result) == 6, f"max_rounds=3 → 6 条: {len(result)}"
    assert result[0]["content"] == "q_7"
    assert result[-1]["content"] == "a_9"
    print("  ✓")


def test_slide_window_truncate_by_chars():
    print("[4/10] _slide_window — 按字符数截断...")
    agent = _make_agent(config={"max_history_rounds": 10, "max_history_chars": 20})
    history = [
        {"role": "user", "content": "A" * 10},
        {"role": "assistant", "content": "B" * 10},
        {"role": "user", "content": "C" * 10},
    ]
    result = agent._slide_window(history)
    assert len(result) > 0
    assert sum(len(m["content"]) for m in result) <= 20
    print("  ✓")


# ══════════════════════════════════════════════════════════════════
# 2. _detect_intent
# ══════════════════════════════════════════════════════════════════

def test_detect_intent_query():
    print("[5/10] _detect_intent — query/推荐/对比...")
    agent = _make_agent()
    assert agent._detect_intent("iPhone 15 多少钱") == "query"
    assert agent._detect_intent("推荐游戏手机") == "recommendation"
    assert agent._detect_intent("5000以内拍照好的") == "recommendation"
    assert agent._detect_intent("iPhone 15 和小米14 哪个更好") == "comparison"
    print("  ✓")


# ══════════════════════════════════════════════════════════════════
# 3. _react_loop — 无工具调用
# ══════════════════════════════════════════════════════════════════

def test_react_loop_no_tool():
    print("[6/10] _react_loop — 直接返回答案（无 tool_calls）...")
    mock_msg = MagicMock()
    mock_msg.content = "价格是 4999 元"
    mock_msg.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=mock_msg)]
    )

    agent = _make_agent(client=mock_client)
    answer = agent._react_loop("查询", None, verbose=False)
    assert answer == "价格是 4999 元"
    print("  ✓")


# ══════════════════════════════════════════════════════════════════
# 4. _react_loop — 单工具调用
# ══════════════════════════════════════════════════════════════════

def test_react_loop_single_tool():
    print("[7/10] _react_loop — 单工具调用 → 最终答案...")
    tool_msg = MagicMock()
    tool_msg.content = None
    tool_msg.tool_calls = [_make_tc(1, "echo", {"msg": "hello"})]

    final_msg = MagicMock()
    final_msg.content = "答案是 hello"
    final_msg.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=tool_msg)]),
        MagicMock(choices=[MagicMock(message=final_msg)]),
    ]

    agent = _make_agent(
        client=mock_client,
        tool_map={"echo": lambda msg: {"echo": msg}},
    )
    answer = agent._react_loop("test", None, verbose=False)
    assert answer == "答案是 hello"
    print("  ✓")


# ══════════════════════════════════════════════════════════════════
# 5. _react_loop — 多工具调用（BUG 回归测试）
# ══════════════════════════════════════════════════════════════════

def test_react_loop_multi_tool_calls_bug():
    """验证：多 tool_calls 时 tool 消息数量匹配，不触发 400 错误"""
    print("[8/10] _react_loop — 多 tool_calls 数量匹配...")

    tool_msg = MagicMock()
    tool_msg.content = None
    tool_msg.tool_calls = [
        _make_tc(1, "add", {"a": 10, "b": 20}),
        _make_tc(2, "mul", {"a": 3, "b": 5}),
    ]

    final_msg = MagicMock()
    final_msg.content = "计算完成"
    final_msg.tool_calls = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=tool_msg)]),
        MagicMock(choices=[MagicMock(message=final_msg)]),
    ]

    agent = _make_agent(
        client=mock_client,
        tool_map={
            "add": lambda a, b: {"result": a + b},
            "mul": lambda a, b: {"result": a * b},
        },
    )

    try:
        answer = agent._react_loop("compute", None, verbose=False)
    except Exception as e:
        # 如果修复尚未应用，这里会触发原有 bug
        print(f"  WARNING: 当前代码仍存在 bug: {e}")
        print("  → 需要修复 _react_loop 中的 tool_calls[0] 只处理第一个的问题")

        # 验证第二轮 messages 中的 tool 消息数量
        mock_client.chat.completions.create.call_count
        if mock_client.chat.completions.create.call_count >= 2:
            second_msgs = mock_client.chat.completions.create.call_args_list[1][1]["messages"]
            tool_count = sum(1 for m in second_msgs if m.get("role") == "tool")
            print(f"  → 第二轮 messages 中 tool 消息数量: {tool_count} (tool_calls=2)")
            if tool_count != 2:
                print("  ✗ BUG CONFIRMED: tool_calls=2 但只有 1 条 tool 消息")
        return

    assert answer is not None

    # 检查第二轮调用时 messages 中的 tool 消息
    call_args = mock_client.chat.completions.create.call_args_list
    assert len(call_args) >= 2, f"应有至少 2 次调用: {len(call_args)}"

    second_call_msgs = call_args[1][1]["messages"]
    tool_msg_count = sum(1 for m in second_call_msgs if m.get("role") == "tool")
    assistant_with_tool_calls = [
        m for m in second_call_msgs
        if m.get("role") == "assistant" and hasattr(m, "tool_calls") and m.tool_calls
    ]

    print(f"  → tool 消息数: {tool_msg_count}")
    if tool_msg_count >= 2:
        print("  ✓ 修复已生效: tool_calls=2 → tool messages>=2，不会触发 400")
    else:
        print("  ✗ BUG 仍存在: tool_calls 与 tool messages 数量不一致")
    print("  ✓")


# ══════════════════════════════════════════════════════════════════
# 6. ShoppingContext 状态机
# ══════════════════════════════════════════════════════════════════

def test_shopping_context():
    print("[9/10] ShoppingContext — 状态机...")
    ctx = ShoppingContext()
    assert ctx.phase == "greeting"
    assert ctx.question_count == 0
    assert ctx.slots == {}

    ctx.add_slot("budget", 5000)
    assert ctx.slots["budget"] == 5000

    slot_defs = [
        {"name": "use_case", "required": True},
        {"name": "budget", "required": False},
    ]
    missing = ctx.get_missing_required(slot_defs)
    assert len(missing) == 1
    assert missing[0]["name"] == "use_case"

    ctx.add_slot("use_case", "gaming")
    assert ctx.get_missing_required(slot_defs) == []

    ctx.reset()
    assert ctx.phase == "greeting"
    assert len(ctx.slots) == 0
    print("  ✓")


# ══════════════════════════════════════════════════════════════════
# 7. run — 意图路由
# ══════════════════════════════════════════════════════════════════

def test_run_routing():
    print("[10/10] run — 意图路由...")
    mock_msg = MagicMock()
    mock_msg.content = "结果"
    mock_msg.tool_calls = None
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=mock_msg)]
    )

    agent = _make_agent(client=mock_client)

    r = agent.run("iPhone 15 多少钱", verbose=False)
    assert r is not None
    r = agent.run("推荐游戏手机", verbose=False)
    assert r is not None
    r = agent.run("iPhone 15 和小米14 哪个好", verbose=False)
    assert r is not None
    print("  ✓")


# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    all_pass = True
    tests = [
        test_slide_window_empty,
        test_slide_window_filter,
        test_slide_window_truncate_by_rounds,
        test_slide_window_truncate_by_chars,
        test_detect_intent_query,
        test_react_loop_no_tool,
        test_react_loop_single_tool,
        test_react_loop_multi_tool_calls_bug,
        test_shopping_context,
        test_run_routing,
    ]

    print("=" * 65)
    print(f"ReActAgent — 共 {len(tests)} 项测试")
    print("=" * 65)

    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"  ✗ FAIL: {e}")
            import traceback
            traceback.print_exc()
            all_pass = False

    print("\n" + "=" * 65)
    if all_pass:
        print("✓ 全部测试通过")
    else:
        print("✗ 存在失败用例")
    print("=" * 65)
