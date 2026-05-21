"""结构化 Trace 事件系统 — 替代 print() 驱动推理可视化"""

import time
import queue
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


class EventType:
    """Trace 事件类型常量"""
    # 入口
    INTENT = "intent"
    MODE_SELECT = "mode_select"

    # ReAct 模式
    REACT_ROUND = "react_round"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REFLECTION = "reflection"

    # Plan-Execute 模式
    PLAN_START = "plan_start"
    PLAN_GENERATED = "plan_generated"
    STEP_START = "step_start"
    STEP_END = "step_end"

    # Phase 3
    SYNTHESIZE_START = "synthesize_start"
    SYNTHESIZE_END = "synthesize_end"

    # M5 Shopping
    SHOPPING_PHASE = "shopping_phase"
    SLOT_FILLED = "slot_filled"

    # 通用
    ERROR = "error"

    # 流式传输控制
    DONE = "done"


@dataclass
class TraceEvent:
    """单个 trace 事件"""
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["elapsed_ms"] = 0  # 由前端相对计算
        return d


class TraceCollector:
    """追踪事件收集器，挂载在 ReActAgent 上"""

    def __init__(self):
        self.events: List[TraceEvent] = []
        self._start_ts: Optional[float] = None
        self._step_start: Dict[int, float] = {}
        self._queue: Optional[queue.Queue] = None
        self._streaming: bool = False

    # ── 流式模式 ──────────────────────────────────────────────────

    def start_stream(self):
        """开启流式模式，事件将通过 queue 实时输出"""
        self._queue = queue.Queue()
        self._streaming = True

    def finish_stream(self, answer: str = ""):
        """结束流式模式，发送 done 事件"""
        if self._queue:
            self._queue.put(TraceEvent(type=EventType.DONE, data={"answer": answer}))
        self._streaming = False

    def iter_events(self):
        """迭代器：从 queue 中获取事件，遇到 DONE 事件时结束"""
        if not self._queue:
            return
        while True:
            ev = self._queue.get()
            yield ev
            if ev.type == EventType.DONE:
                break

    # ── 工厂方法 ──────────────────────────────────────────────────

    def add(self, event_type: str, **data) -> TraceEvent:
        ev = TraceEvent(type=event_type, data=data)
        self.events.append(ev)
        if self._streaming and self._queue:
            self._queue.put(ev)
        return ev

    def intent(self, intent: str, query: str = "", **extra) -> TraceEvent:
        return self.add(EventType.INTENT, intent=intent, query=query, **extra)

    def mode_select(self, mode: str, reason: str = "", model: str = "", **extra) -> TraceEvent:
        return self.add(EventType.MODE_SELECT, mode=mode, reason=reason, model=model, **extra)

    def react_round(self, round_num: int, thought: str, model: str = "", **extra) -> TraceEvent:
        return self.add(EventType.REACT_ROUND, round=round_num, thought=thought[:300], model=model, **extra)

    def tool_call(self, tool_name: str, args: dict, round_num: int = 0, step: int = 0, **extra) -> TraceEvent:
        return self.add(EventType.TOOL_CALL, tool=tool_name, args=args, round=round_num, step=step, **extra)

    def tool_result(self, tool_name: str, found: bool, match_count: int = 0,
                    cheapest: dict = None, error: str = "", summary: str = "",
                    round_num: int = 0, step: int = 0, **extra) -> TraceEvent:
        return self.add(EventType.TOOL_RESULT,
                        tool=tool_name, found=found, match_count=match_count,
                        cheapest=cheapest, error=error, summary=summary[:300],
                        round=round_num, step=step, **extra)

    def reflection(self, tool_name: str, retry_count: int, action: str, reasoning: str = "", **extra) -> TraceEvent:
        return self.add(EventType.REFLECTION, tool=tool_name, retry_count=retry_count,
                        action=action, reasoning=reasoning, **extra)

    def plan_start(self, **extra) -> TraceEvent:
        return self.add(EventType.PLAN_START, **extra)

    def plan_generated(self, steps: list, model: str = "", **extra) -> TraceEvent:
        return self.add(EventType.PLAN_GENERATED, steps=steps, step_count=len(steps), model=model, **extra)

    def step_start(self, step_num: int, tool: str, purpose: str = "", depends_on: int = None, **extra) -> TraceEvent:
        self._step_start[step_num] = time.time()
        return self.add(EventType.STEP_START, step=step_num, tool=tool,
                        purpose=purpose, depends_on=depends_on, **extra)

    def step_end(self, step_num: int, success: bool, summary: str = "", error: str = "", **extra) -> TraceEvent:
        elapsed = 0.0
        if step_num in self._step_start:
            elapsed = round((time.time() - self._step_start.pop(step_num)) * 1000)
        return self.add(EventType.STEP_END, step=step_num, success=success,
                        summary=summary[:300], error=error, elapsed_ms=elapsed, **extra)

    def synthesize_start(self, model: str = "", **extra) -> TraceEvent:
        return self.add(EventType.SYNTHESIZE_START, model=model, **extra)

    def synthesize_end(self, char_count: int = 0, model: str = "", **extra) -> TraceEvent:
        return self.add(EventType.SYNTHESIZE_END, char_count=char_count, model=model, **extra)

    def shopping_phase(self, phase: str, from_phase: str = "", **extra) -> TraceEvent:
        return self.add(EventType.SHOPPING_PHASE, phase=phase, from_phase=from_phase, **extra)

    def slot_filled(self, slot_name: str, value, phase: str = "", **extra) -> TraceEvent:
        return self.add(EventType.SLOT_FILLED, slot=slot_name, value=str(value), phase=phase, **extra)

    def error(self, message: str, context: str = "", **extra) -> TraceEvent:
        return self.add(EventType.ERROR, message=message, context=context, **extra)

    # ── 工具方法 ──────────────────────────────────────────────────

    def reset(self):
        self.events.clear()
        self._step_start.clear()
        self._start_ts = time.time()

    def to_list(self) -> List[dict]:
        return [e.to_dict() for e in self.events]

    def to_text(self) -> str:
        """将 trace 事件拼接为可读文本（向前兼容旧前端）"""
        lines = []
        for e in self.events:
            t = e.type
            d = e.data
            if t == EventType.INTENT:
                lines.append(f"[Intent: {d.get('intent', '?')}] 查询: {d.get('query', '')[:80]}")
            elif t == EventType.MODE_SELECT:
                model_hint = f" (model: {d['model']})" if d.get("model") else ""
                lines.append(f"[Mode] {d.get('mode', '?')}{model_hint} — {d.get('reason', '')}")
            elif t == EventType.REACT_ROUND:
                lines.append(f"\n【Round {d.get('round', '?')} - Thought】{d.get('thought', '')}")
            elif t == EventType.TOOL_CALL:
                step_hint = f"Step {d['step']} " if d.get("step") else ""
                lines.append(f"  ├─【Action{step_hint}】{d.get('tool', '?')}({d.get('args', {})})")
            elif t == EventType.TOOL_RESULT:
                if d.get("found"):
                    lines.append(f"  └─【Observation】找到 {d.get('match_count', '?')} 个匹配")
                elif d.get("error"):
                    lines.append(f"  └─【Observation】错误: {d['error'][:100]}")
                else:
                    lines.append(f"  └─【Observation】未找到匹配")
            elif t == EventType.REFLECTION:
                lines.append(f"【Reflection】{d.get('action', '?')} — {d.get('reasoning', '')}")
            elif t == EventType.PLAN_GENERATED:
                lines.append(f"[Phase 1] 计划 {d.get('step_count', '?')} 步 (model: {d.get('model', '?')})")
                for s in d.get("steps", []):
                    dep = f" (依赖 step {s.get('depends_on')})" if s.get("depends_on") else ""
                    lines.append(f"  Step {s.get('step', '?')}: {s.get('tool', '?')}{dep} — {s.get('purpose', '')}")
            elif t == EventType.STEP_START:
                lines.append(f"\n  ── Step {d.get('step', '?')}: {d.get('purpose', d.get('tool', ''))} ──")
            elif t == EventType.STEP_END:
                status = "✓" if d.get("success") else "✗"
                elapsed = f" ({d.get('elapsed_ms', 0)}ms)" if d.get("elapsed_ms") else ""
                lines.append(f"    {status} Step {d.get('step', '?')} 完成{elapsed}")
            elif t == EventType.SYNTHESIZE_START:
                lines.append(f"\n[Phase 3] 综合分析 (model: {d.get('model', '?')})")
            elif t == EventType.SYNTHESIZE_END:
                lines.append(f"[Phase 3] 答案生成完成 ({d.get('char_count', 0)} 字符)")
            elif t == EventType.SHOPPING_PHASE:
                lines.append(f"[Shopping] {d.get('from_phase', '')} → {d.get('phase', '')}")
            elif t == EventType.SLOT_FILLED:
                lines.append(f"[Shopping] 槽位 {d.get('slot', '?')} = {d.get('value', '?')}")
            elif t == EventType.ERROR:
                lines.append(f"[Error] {d.get('context', '')}: {d.get('message', '')}")
        return "\n".join(lines)
