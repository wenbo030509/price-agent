"""
测试 L1 结构化 Trace 事件 + L2 SSE 流式传输

覆盖:
  - EventType 常量完整性
  - TraceEvent 创建 / to_dict / JSON 序列化
  - TraceCollector 工厂方法 / to_list / to_text / reset
  - 流式模式 start_stream → iter_events → finish_stream
  - ReActAgent trace 集成（mock LLM）
  - run_stream 生成器行为
"""
import json
import sys
import os
import time
import threading
from unittest.mock import MagicMock, patch
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.trace import TraceCollector, TraceEvent, EventType
from agent.react_engine import ReActAgent, ShoppingContext

_TCArg = namedtuple("_TCArg", ["name", "arguments"])


# ══════════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════════

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
# 1. EventType 常量
# ══════════════════════════════════════════════════════════════════

def test_event_type_constants():
    """EventType 包含所有预期的类型常量"""
    assert EventType.INTENT == "intent"
    assert EventType.MODE_SELECT == "mode_select"
    assert EventType.REACT_ROUND == "react_round"
    assert EventType.TOOL_CALL == "tool_call"
    assert EventType.TOOL_RESULT == "tool_result"
    assert EventType.REFLECTION == "reflection"
    assert EventType.PLAN_START == "plan_start"
    assert EventType.PLAN_GENERATED == "plan_generated"
    assert EventType.STEP_START == "step_start"
    assert EventType.STEP_END == "step_end"
    assert EventType.SYNTHESIZE_START == "synthesize_start"
    assert EventType.SYNTHESIZE_END == "synthesize_end"
    assert EventType.SHOPPING_PHASE == "shopping_phase"
    assert EventType.SLOT_FILLED == "slot_filled"
    assert EventType.ERROR == "error"
    assert EventType.DONE == "done"


# ══════════════════════════════════════════════════════════════════
# 2. TraceEvent
# ══════════════════════════════════════════════════════════════════

def test_trace_event_basic():
    """TraceEvent 基本创建"""
    ev = TraceEvent(type="test", data={"key": "value"})
    assert ev.type == "test"
    assert ev.data == {"key": "value"}
    assert isinstance(ev.ts, float)
    assert ev.ts > 0


def test_trace_event_defaults():
    """TraceEvent 默认值"""
    ev = TraceEvent(type="empty")
    assert ev.data == {}
    assert ev.type == "empty"


def test_trace_event_to_dict():
    """to_dict 包含 type/data/ts/elapsed_ms 四个字段"""
    ev = TraceEvent(type="intent", data={"intent": "query"})
    d = ev.to_dict()
    assert d["type"] == "intent"
    assert d["data"] == {"intent": "query"}
    assert "ts" in d
    assert d["elapsed_ms"] == 0


def test_trace_event_json_serializable():
    """TraceEvent.to_dict 结果可 JSON 序列化"""
    ev = TraceEvent(type="tool_result", data={
        "found": True, "match_count": 5,
        "cheapest": {"platform_name": "拼多多", "platform_price": 5750},
        "summary": "找到 5 个匹配",
    })
    d = ev.to_dict()
    json_str = json.dumps(d, ensure_ascii=False)
    parsed = json.loads(json_str)
    assert parsed["type"] == "tool_result"
    assert parsed["data"]["match_count"] == 5
    assert parsed["data"]["cheapest"]["platform_price"] == 5750


def test_trace_event_ts_is_float():
    """TraceEvent.ts 是 Unix 时间戳"""
    t0 = time.time()
    ev = TraceEvent(type="test")
    assert t0 <= ev.ts <= time.time() + 0.1


# ══════════════════════════════════════════════════════════════════
# 3. TraceCollector — 基本操作
# ══════════════════════════════════════════════════════════════════

def test_collector_init_empty():
    """新 TraceCollector 事件列表为空"""
    tc = TraceCollector()
    assert len(tc.events) == 0
    assert tc.to_list() == []


def test_collector_add():
    """add() 追加事件到列表"""
    tc = TraceCollector()
    ev = tc.add("test_type", key="val")
    assert len(tc.events) == 1
    assert tc.events[0] is ev
    assert tc.events[0].type == "test_type"
    assert tc.events[0].data == {"key": "val"}


def test_collector_add_multiple():
    """多次 add 按顺序排列"""
    tc = TraceCollector()
    tc.add("a", n=1)
    tc.add("b", n=2)
    tc.add("c", n=3)
    assert len(tc.events) == 3
    assert [e.type for e in tc.events] == ["a", "b", "c"]


def test_collector_to_list():
    """to_list 返回 dict 列表"""
    tc = TraceCollector()
    tc.add("t1", a=1)
    tc.add("t2", b=2)
    lst = tc.to_list()
    assert len(lst) == 2
    assert lst[0]["type"] == "t1"
    assert lst[1]["type"] == "t2"
    assert all("ts" in d for d in lst)
    assert all("elapsed_ms" in d for d in lst)


def test_collector_to_text_empty():
    """空事件列表 to_text 返回空字符串"""
    tc = TraceCollector()
    assert tc.to_text() == ""


def test_collector_reset_clears_events():
    """reset 清空事件列表"""
    tc = TraceCollector()
    tc.intent("query", "test")
    assert len(tc.events) == 1
    tc.reset()
    assert len(tc.events) == 0


def test_collector_reset_clears_step_timing():
    """reset 清空步骤计时"""
    tc = TraceCollector()
    tc.step_start(step_num=1, tool="test_tool")
    assert 1 in tc._step_start
    tc.reset()
    assert 1 not in tc._step_start


def test_collector_reset_preserves_streaming_state():
    """reset 不影响 streaming 状态（queue 和 _streaming 标志独立）"""
    tc = TraceCollector()
    tc.start_stream()
    queue_before = tc._queue
    tc.reset()
    assert tc._streaming  # reset 不改变 streaming 状态
    assert tc._queue is queue_before  # queue 不变
    tc.finish_stream("ok")


# ══════════════════════════════════════════════════════════════════
# 4. TraceCollector — 工厂方法
# ══════════════════════════════════════════════════════════════════

def test_factory_intent():
    tc = TraceCollector()
    ev = tc.intent(intent="query", query="iPhone 价格")
    assert ev.type == EventType.INTENT
    assert ev.data["intent"] == "query"
    assert ev.data["query"] == "iPhone 价格"


def test_factory_mode_select():
    tc = TraceCollector()
    ev = tc.mode_select(mode="plan_execute", reason="复杂查询", model="gpt-4")
    assert ev.type == EventType.MODE_SELECT
    assert ev.data["mode"] == "plan_execute"
    assert ev.data["reason"] == "复杂查询"
    assert ev.data["model"] == "gpt-4"


def test_factory_react_round():
    tc = TraceCollector()
    ev = tc.react_round(round_num=2, thought="需要比价", model="test-model")
    assert ev.type == EventType.REACT_ROUND
    assert ev.data["round"] == 2
    assert "需要比价" in ev.data["thought"]
    assert ev.data["model"] == "test-model"


def test_factory_react_round_truncates_thought():
    """thought 超过 300 字符时截断"""
    tc = TraceCollector()
    long_thought = "A" * 500
    ev = tc.react_round(round_num=1, thought=long_thought)
    assert len(ev.data["thought"]) == 300


def test_factory_tool_call():
    tc = TraceCollector()
    ev = tc.tool_call(tool_name="search", args={"q": "iPhone"}, round_num=1, step=2)
    assert ev.type == EventType.TOOL_CALL
    assert ev.data["tool"] == "search"
    assert ev.data["args"] == {"q": "iPhone"}
    assert ev.data["round"] == 1
    assert ev.data["step"] == 2


def test_factory_tool_result_found():
    tc = TraceCollector()
    ev = tc.tool_result(
        tool_name="search", found=True, match_count=10,
        cheapest={"platform_name": "京东", "platform_price": 5999},
        summary="找到 10 个结果",
    )
    assert ev.type == EventType.TOOL_RESULT
    assert ev.data["found"] is True
    assert ev.data["match_count"] == 10
    assert ev.data["cheapest"]["platform_name"] == "京东"


def test_factory_tool_result_empty():
    tc = TraceCollector()
    ev = tc.tool_result(tool_name="search", found=False, summary="未找到")
    assert ev.data["found"] is False
    assert ev.data["match_count"] == 0


def test_factory_tool_result_error():
    tc = TraceCollector()
    ev = tc.tool_result(tool_name="search", found=False, error="连接超时")
    assert ev.data["error"] == "连接超时"


def test_factory_tool_result_truncates_summary():
    """summary 超过 300 字符时截断"""
    tc = TraceCollector()
    long_summary = "x" * 500
    ev = tc.tool_result(tool_name="t", found=True, summary=long_summary)
    assert len(ev.data["summary"]) == 300


def test_factory_reflection():
    tc = TraceCollector()
    ev = tc.reflection(tool_name="search", retry_count=2, action="retry", reasoning="换关键词")
    assert ev.type == EventType.REFLECTION
    assert ev.data["tool"] == "search"
    assert ev.data["retry_count"] == 2
    assert ev.data["action"] == "retry"


def test_factory_plan_generated():
    tc = TraceCollector()
    steps = [
        {"step": 1, "tool": "search", "depends_on": None, "purpose": "查询商品"},
        {"step": 2, "tool": "compare", "depends_on": 1, "purpose": "比价"},
    ]
    ev = tc.plan_generated(steps=steps, model="plan-model")
    assert ev.type == EventType.PLAN_GENERATED
    assert ev.data["step_count"] == 2
    assert ev.data["steps"] == steps
    assert ev.data["model"] == "plan-model"


def test_factory_step_start():
    tc = TraceCollector()
    ev = tc.step_start(step_num=3, tool="compare", purpose="比价", depends_on=1, group="dependent")
    assert ev.type == EventType.STEP_START
    assert ev.data["step"] == 3
    assert ev.data["tool"] == "compare"
    assert ev.data["purpose"] == "比价"
    assert ev.data["depends_on"] == 1
    assert ev.data["group"] == "dependent"
    # 记录步骤开始时间
    assert 3 in tc._step_start


def test_factory_step_end_success():
    tc = TraceCollector()
    # step_start first to set timing
    tc.step_start(step_num=1, tool="t")
    time.sleep(0.01)
    ev = tc.step_end(step_num=1, success=True, summary="找到 5 个")
    assert ev.type == EventType.STEP_END
    assert ev.data["success"] is True
    assert ev.data["elapsed_ms"] > 0


def test_factory_step_end_failure():
    tc = TraceCollector()
    tc.step_start(step_num=1, tool="t")
    ev = tc.step_end(step_num=1, success=False, error="超时")
    assert ev.data["success"] is False
    assert ev.data["error"] == "超时"


def test_factory_step_end_no_start():
    """没有 step_start 时 elapsed_ms 为 0"""
    tc = TraceCollector()
    ev = tc.step_end(step_num=99, success=True)
    assert ev.data["elapsed_ms"] == 0


def test_factory_synthesize():
    tc = TraceCollector()
    ev1 = tc.synthesize_start(model="s-model")
    ev2 = tc.synthesize_end(char_count=512, model="s-model")
    assert ev1.type == EventType.SYNTHESIZE_START
    assert ev1.data["model"] == "s-model"
    assert ev2.type == EventType.SYNTHESIZE_END
    assert ev2.data["char_count"] == 512


def test_factory_shopping_phase():
    tc = TraceCollector()
    ev = tc.shopping_phase(phase="slot_filling", from_phase="greeting")
    assert ev.type == EventType.SHOPPING_PHASE
    assert ev.data["phase"] == "slot_filling"
    assert ev.data["from_phase"] == "greeting"


def test_factory_slot_filled():
    tc = TraceCollector()
    ev = tc.slot_filled(slot_name="budget_max", value=5000, phase="slot_filling")
    assert ev.type == EventType.SLOT_FILLED
    assert ev.data["slot"] == "budget_max"
    # value 被转为字符串
    assert ev.data["value"] == "5000"


def test_factory_slot_filled_str_value():
    tc = TraceCollector()
    ev = tc.slot_filled(slot_name="brand", value="Apple")
    assert ev.data["value"] == "Apple"


def test_factory_error():
    tc = TraceCollector()
    ev = tc.error(message="数据库连接失败", context="search")
    assert ev.type == EventType.ERROR
    assert ev.data["message"] == "数据库连接失败"
    assert ev.data["context"] == "search"


def test_factory_plan_start():
    tc = TraceCollector()
    ev = tc.plan_start()
    assert ev.type == EventType.PLAN_START


# ══════════════════════════════════════════════════════════════════
# 5. TraceCollector — to_text 文本输出
# ══════════════════════════════════════════════════════════════════

def test_to_text_intent():
    tc = TraceCollector()
    tc.intent(intent="comparison", query="对比 iPhone 和 小米")
    text = tc.to_text()
    assert "comparison" in text
    assert "对比 iPhone 和 小米" in text


def test_to_text_mode_select():
    tc = TraceCollector()
    tc.mode_select(mode="react", reason="简单查询", model="gpt-4")
    text = tc.to_text()
    assert "react" in text
    assert "gpt-4" in text


def test_to_text_mode_select_no_model():
    tc = TraceCollector()
    tc.mode_select(mode="react", reason="简单查询")
    text = tc.to_text()
    assert "(model:" not in text  # 无 model 时不显示


def test_to_text_tool_result_found():
    tc = TraceCollector()
    tc.tool_result(tool_name="search", found=True, match_count=10)
    text = tc.to_text()
    assert "找到" in text
    assert "10" in text


def test_to_text_tool_result_empty():
    tc = TraceCollector()
    tc.tool_result(tool_name="search", found=False)
    text = tc.to_text()
    assert "未找到匹配" in text


def test_to_text_tool_result_error():
    tc = TraceCollector()
    tc.tool_result(tool_name="search", found=False, error="timeout")
    text = tc.to_text()
    assert "错误" in text
    assert "timeout" in text


def test_to_text_plan_generated_with_steps():
    tc = TraceCollector()
    tc.plan_generated(steps=[
        {"step": 1, "tool": "search", "depends_on": None, "purpose": "查商品"},
        {"step": 2, "tool": "compare", "depends_on": 1, "purpose": "比价"},
    ], model="p-model")
    text = tc.to_text()
    assert "2 步" in text
    assert "Step 1" in text
    assert "Step 2" in text
    assert "依赖 step 1" in text


def test_to_text_step_end():
    tc = TraceCollector()
    tc.step_start(step_num=1, tool="t")
    time.sleep(0.01)
    tc.step_end(step_num=1, success=True, summary="完成")
    text = tc.to_text()
    assert "✓" in text
    assert "Step 1" in text


def test_to_text_shopping_phase():
    tc = TraceCollector()
    tc.shopping_phase(phase="searching", from_phase="slot_filling")
    text = tc.to_text()
    assert "Shopping" in text
    assert "searching" in text


def test_to_text_error():
    tc = TraceCollector()
    tc.error(message="失败", context="init")
    text = tc.to_text()
    assert "Error" in text
    assert "失败" in text


def test_to_text_multiple_events():
    """多个事件输出完整文本"""
    tc = TraceCollector()
    tc.intent("query", "test")
    tc.mode_select("react", "test")
    tc.react_round(1, "思考中", "m")
    text = tc.to_text()
    assert "Intent" in text
    assert "Mode" in text
    assert "Round 1" in text


# ══════════════════════════════════════════════════════════════════
# 6. L2 — 流式模式
# ══════════════════════════════════════════════════════════════════

def test_start_stream_creates_queue():
    tc = TraceCollector()
    tc.start_stream()
    assert tc._streaming
    assert tc._queue is not None


def test_stream_add_pushes_to_queue():
    """流式模式下 add() 同时写入 events 列表和 queue"""
    tc = TraceCollector()
    tc.start_stream()

    ev = tc.intent("query", "test")

    # events 列表中有
    assert len(tc.events) == 1

    # queue 中也有
    from_queue = tc._queue.get(timeout=1)
    assert from_queue is ev
    assert from_queue.type == EventType.INTENT


def test_iter_events_yields_in_order():
    """iter_events 按序 yield 事件"""
    tc = TraceCollector()
    tc.start_stream()
    tc.intent("query", "t1")
    tc.mode_select("react", "r1")
    tc.tool_call("search", {"q": "x"}, round_num=1)
    tc.finish_stream("answer")

    events = list(tc.iter_events())
    types = [e.type for e in events]
    assert types == [
        EventType.INTENT,
        EventType.MODE_SELECT,
        EventType.TOOL_CALL,
        EventType.DONE,
    ]


def test_finish_stream_sends_done():
    """finish_stream 发送 DONE 事件并携带 answer"""
    tc = TraceCollector()
    tc.start_stream()
    tc.finish_stream("最终答案")

    done_ev = tc._queue.get(timeout=1)
    assert done_ev.type == EventType.DONE
    assert done_ev.data["answer"] == "最终答案"


def test_finish_stream_stops_streaming():
    tc = TraceCollector()
    tc.start_stream()
    tc.finish_stream("ok")
    assert not tc._streaming


def test_iter_events_stops_at_done():
    tc = TraceCollector()
    tc.start_stream()
    tc.intent("query", "t")
    tc.finish_stream("answer")

    events = list(tc.iter_events())
    assert len(events) == 2  # intent + done


def test_stream_thread_safety():
    """多线程写入 event，主线程读取 — 无竞态条件"""
    tc = TraceCollector()
    tc.start_stream()

    def writer():
        for i in range(5):
            tc.add(f"event_{i}", index=i)
            time.sleep(0.005)
        tc.finish_stream("done")

    t = threading.Thread(target=writer, daemon=True)
    t.start()

    events = list(tc.iter_events())
    t.join(timeout=2)

    types = [e.type for e in events]
    assert types[0] == "event_0"
    assert types[4] == "event_4"
    assert types[5] == EventType.DONE


def test_stream_events_also_in_list():
    """流式模式下业务事件同时存在于 events 列表和 queue，DONE 仅走 queue"""
    tc = TraceCollector()
    tc.start_stream()
    tc.intent("query", "t")
    tc.mode_select("react", "r")
    tc.finish_stream("a")

    # events 列表只有业务事件（DONE 是控制信号，不经过 add）
    assert len(tc.events) == 2  # intent + mode_select

    # queue 迭代包含全部事件（含 DONE）
    queue_events = list(tc.iter_events())
    assert len(queue_events) == 3  # intent + mode_select + done
    assert queue_events[-1].type == EventType.DONE


def test_stream_no_events_then_done():
    """无业务事件时直接 finish，queue 只含 DONE"""
    tc = TraceCollector()
    tc.start_stream()
    tc.finish_stream("empty")

    events = list(tc.iter_events())
    assert len(events) == 1
    assert events[0].type == EventType.DONE


def test_iter_events_no_queue_returns_none():
    """未调用 start_stream 时 iter_events 直接返回（不 yield）"""
    tc = TraceCollector()
    events = list(tc.iter_events())
    assert events == []


def test_stream_add_after_finish_not_queued():
    """finish 后 add 不再推入 queue"""
    tc = TraceCollector()
    tc.start_stream()
    tc.finish_stream("done")
    # 消费完 queue
    list(tc.iter_events())

    tc.intent("late", "should not be in queue")
    assert tc._queue.qsize() == 0  # 不再推入


# ══════════════════════════════════════════════════════════════════
# 7. ReActAgent trace 集成（mock LLM）
# ══════════════════════════════════════════════════════════════════

def _mock_response(content=None, tool_calls=None):
    """构造 mock OpenAI chat completion response"""
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    return resp


def test_agent_run_emits_intent_and_mode_select():
    """run() 总是发送 intent + mode_select 事件"""
    agent = _make_agent()
    resp = _mock_response(content="答案是 42")
    agent.client.chat.completions.create.return_value = resp

    agent.run("iPhone 15 多少钱", verbose=False)

    assert len(agent.trace.events) >= 2
    assert agent.trace.events[0].type == EventType.INTENT
    types = [e.type for e in agent.trace.events]
    assert EventType.MODE_SELECT in types


def test_agent_run_resets_trace():
    """每次 run() 先 reset trace"""
    agent = _make_agent()

    # 第一次 run
    resp1 = _mock_response(content="第一次")
    agent.client.chat.completions.create.return_value = resp1
    agent.trace.add("old_event")
    agent.run("query1", verbose=False)
    # 旧事件被清除
    assert "old_event" not in [e.type for e in agent.trace.events]

    # 第二次 run
    resp2 = _mock_response(content="第二次")
    agent.client.chat.completions.create.return_value = resp2
    agent.run("query2", verbose=False)
    assert agent.trace.events[0].type == EventType.INTENT


def test_react_loop_emits_round_and_tool_events():
    """_react_loop 模式产生 react_round + tool_call + tool_result 事件"""
    agent = _make_agent(
        tools=[{
            "type": "function",
            "function": {
                "name": "mock_search",
                "description": "mock",
                "parameters": {"type": "object", "properties": {}}
            }
        }],
        tool_map={
            "mock_search": lambda **kw: {
                "raw_data": {"found": True, "total_matches": 3,
                             "cheapest": {"platform_name": "京东", "platform_price": 99}}
            }
        },
        max_round=2,
    )

    # Round 1: tool call → result → Round 2: final answer
    tc1 = _make_tc(1, "mock_search", {"q": "test"})
    resp1 = _mock_response(content="需要查询", tool_calls=[tc1])
    resp2 = _mock_response(content="答案是 XX")
    agent.client.chat.completions.create.side_effect = [resp1, resp2]

    result = agent.run("搜索商品", verbose=False)

    types = [e.type for e in agent.trace.events]
    assert EventType.INTENT in types
    assert EventType.MODE_SELECT in types
    assert EventType.REACT_ROUND in types
    assert EventType.TOOL_CALL in types
    assert EventType.TOOL_RESULT in types
    assert result == "答案是 XX"


def test_react_loop_tool_result_has_cheapest():
    """tool_result 包含 cheapest 信息"""
    agent = _make_agent(
        tools=[{
            "type": "function",
            "function": {
                "name": "search",
                "description": "s",
                "parameters": {"type": "object", "properties": {}}
            }
        }],
        tool_map={"search": lambda **kw: {
            "raw_data": {"found": True, "total_matches": 5,
                         "cheapest": {"platform_name": "拼多多", "platform_price": 5750}}
        }},
    )
    tc = _make_tc(0, "search", {})
    resp1 = _mock_response(content="查价", tool_calls=[tc])
    resp2 = _mock_response(content="拼多多最便宜")
    agent.client.chat.completions.create.side_effect = [resp1, resp2]

    agent.run("iPhone", verbose=False)

    tool_result_ev = [e for e in agent.trace.events if e.type == EventType.TOOL_RESULT][0]
    assert tool_result_ev.data["found"] is True
    assert tool_result_ev.data["match_count"] == 5
    assert tool_result_ev.data["cheapest"]["platform_price"] == 5750


def test_react_loop_empty_result_emits_reflection():
    """空结果触发 reflection 事件"""
    agent = _make_agent(
        tools=[{
            "type": "function",
            "function": {
                "name": "search",
                "description": "s",
                "parameters": {"type": "object", "properties": {}}
            }
        }],
        tool_map={"search": lambda **kw: {"raw_data": {"found": False, "total_matches": 0}}},
        config={
            "max_history_rounds": 5, "max_history_chars": 1000,
            "max_reflection_retries": 1,  # 允许 1 次重试
            "auto_relax_attributes": False, "max_step_react_rounds": 2,
            "max_plan_steps": 3,
        },
    )
    tc = _make_tc(0, "search", {})
    resp1 = _mock_response(content="查询", tool_calls=[tc])
    resp2 = _mock_response(content="答案")
    agent.client.chat.completions.create.side_effect = [resp1, resp2]

    agent.run("不存在的商品", verbose=False)

    types = [e.type for e in agent.trace.events]
    assert EventType.REFLECTION in types, f"expected reflection, got types: {types}"


def test_agent_run_routing_comparison():
    """comparison 意图路由到 plan_execute 模式"""
    agent = _make_agent()
    agent.client.chat.completions.create.return_value = _mock_response(
        content='{"complexity": "simple"}'  # plan 判定 simple → 回退 react
    )
    # 但先触发 comparison 意图
    agent._is_complex = MagicMock(return_value=True)
    agent._count_models = MagicMock(return_value=2)

    resp_react = _mock_response(content="对比结果")
    agent.client.chat.completions.create.side_effect = [
        _mock_response(content='{"complexity": "simple"}'),  # plan
        resp_react,  # react fallback
        resp_react,
    ]

    agent.run("iPhone 和小米 哪个好", verbose=False)

    mode_ev = [e for e in agent.trace.events if e.type == EventType.MODE_SELECT]
    assert len(mode_ev) >= 1
    # 第一个 mode_select 是 plan_execute，第二个是回退 react
    assert mode_ev[0].data["mode"] == "plan_execute"


def test_plan_execute_emits_plan_and_step_events():
    """Plan-Execute 模式产生 plan + step_start/step_end 事件"""
    agent = _make_agent(
        tools=[{
            "type": "function",
            "function": {
                "name": "search",
                "description": "s",
                "parameters": {"type": "object", "properties": {}}
            }
        }],
        tool_map={"search": lambda **kw: {
            "raw_data": {"found": True, "total_matches": 1,
                         "cheapest": {"platform_name": "京东", "platform_price": 99}}
        }},
    )
    agent._is_complex = MagicMock(return_value=True)
    agent._count_models = MagicMock(return_value=2)

    # Phase 1: 返回 complex plan
    plan_resp = _mock_response(content=json.dumps({
        "complexity": "complex",
        "plan": [
            {"step": 1, "tool": "search", "args": {"q": "a"}, "depends_on": None, "purpose": "查A"},
            {"step": 2, "tool": "search", "args": {"q": "b"}, "depends_on": None, "purpose": "查B"},
        ]
    }))
    # Phase 3: synthesize
    synth_resp = _mock_response(content="最终对比结果")

    agent.client.chat.completions.create.side_effect = [plan_resp, synth_resp]

    agent.run("对比 A 和 B", verbose=False)

    types = [e.type for e in agent.trace.events]
    assert EventType.PLAN_START in types
    assert EventType.PLAN_GENERATED in types
    assert EventType.STEP_START in types
    assert EventType.STEP_END in types
    assert EventType.SYNTHESIZE_START in types
    assert EventType.SYNTHESIZE_END in types

    # 验证 plan steps 数量
    plan_ev = [e for e in agent.trace.events if e.type == EventType.PLAN_GENERATED][0]
    assert plan_ev.data["step_count"] == 2


def test_agent_trace_to_list_json_serializable():
    """完整 run 后的 trace 可 JSON 序列化"""
    agent = _make_agent()
    resp = _mock_response(content="答案")
    agent.client.chat.completions.create.return_value = resp

    agent.run("test", verbose=False)

    trace_list = agent.trace.to_list()
    json_str = json.dumps(trace_list, ensure_ascii=False)
    parsed = json.loads(json_str)
    assert len(parsed) == len(trace_list)
    assert all("type" in e for e in parsed)


# ══════════════════════════════════════════════════════════════════
# 8. L2 — run_stream 生成器
# ══════════════════════════════════════════════════════════════════

def test_run_stream_yields_events():
    """run_stream 生成器按序 yield 事件"""
    agent = _make_agent()
    resp1 = _mock_response(content="需要查价")
    resp2 = _mock_response(content="最终答案")
    agent.client.chat.completions.create.side_effect = [resp1, resp2]

    gen = agent.run_stream("iPhone 价格", verbose=False)

    events = list(gen)
    types = [e.type for e in events]
    assert EventType.INTENT in types
    assert EventType.MODE_SELECT in types
    assert EventType.DONE in types


def test_run_stream_done_contains_answer():
    """DONE 事件携带最终 answer"""
    agent = _make_agent()
    resp1 = _mock_response(content="直接答案")
    agent.client.chat.completions.create.return_value = resp1

    gen = agent.run_stream("test", verbose=False)
    events = list(gen)

    done_ev = events[-1]
    assert done_ev.type == EventType.DONE
    assert done_ev.data["answer"] == "直接答案"


def test_run_stream_thread_exception_handled():
    """agent 线程异常时 DONE 事件携带错误信息"""
    agent = _make_agent()
    # 让 run() 抛异常
    agent._detect_intent = MagicMock(side_effect=RuntimeError("模拟异常"))

    gen = agent.run_stream("query", verbose=False)
    events = list(gen)

    done_ev = events[-1]
    assert done_ev.type == EventType.DONE
    assert "处理出错" in done_ev.data.get("answer", "")


def test_run_stream_events_are_trace_events():
    """run_stream yield 的对象是 TraceEvent 实例"""
    agent = _make_agent()
    resp1 = _mock_response(content="答案")
    agent.client.chat.completions.create.return_value = resp1

    gen = agent.run_stream("test", verbose=False)
    for ev in gen:
        assert isinstance(ev, TraceEvent)


def test_run_stream_to_dict_all_events():
    """run_stream 每个事件都可 to_dict"""
    agent = _make_agent()
    resp1 = _mock_response(content="答案")
    agent.client.chat.completions.create.return_value = resp1

    gen = agent.run_stream("test", verbose=False)
    for ev in gen:
        d = ev.to_dict()
        assert isinstance(d, dict)
        assert "type" in d
        assert "data" in d
        assert "ts" in d
        assert "elapsed_ms" in d


def test_run_stream_resets_between_calls():
    """连续两次 run_stream 互不干扰"""
    agent = _make_agent()
    resp = _mock_response(content="答案")
    agent.client.chat.completions.create.return_value = resp

    # First run
    gen1 = agent.run_stream("q1", verbose=False)
    events1 = list(gen1)
    n1 = len(events1)

    # Second run
    gen2 = agent.run_stream("q2", verbose=False)
    events2 = list(gen2)
    n2 = len(events2)

    # 两次事件数量接近（由于时间戳差异可能有微小差别）
    assert abs(n1 - n2) <= 2
    # 第二次不包括第一次的事件
    types2 = [e.type for e in events2]
    assert EventType.INTENT in types2


# ══════════════════════════════════════════════════════════════════
# 9. ShoppingContext 不变（回归）
# ══════════════════════════════════════════════════════════════════

def test_shopping_context_unaffected():
    """ShoppingContext 行为不变"""
    ctx = ShoppingContext()
    assert ctx.phase == "greeting"
    ctx.add_slot("brand", "Apple")
    assert ctx.slots["brand"] == "Apple"
    ctx.reset()
    assert ctx.phase == "greeting"
    assert len(ctx.slots) == 0
