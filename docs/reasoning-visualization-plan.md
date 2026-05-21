# 推理可视化增强方案

## 一、当前能力盘点

### 1.1 后端推理输出

`react_engine.py` 通过 `print()` 输出文本到 stdout，`app.py` 捕获后作为 `reasoning` 字段返回前端：

```
[Intent: comparison] 启用 Plan-Execute 对比模式
[Phase 1] 生成执行计划...
[Phase 1] 计划 3 步：
  Step 1: semantic_product_search — 筛选游戏手机...
  Step 2: multi_platform_price_comparison (依赖 step 1) — 比价...
[Phase 2] 执行计划（每 Step 独立 mini-ReAct）...
  并行执行 2 个 Step...
  ✓ Step 1: semantic_product_search 完成
  Step 3: multi_platform_price_comparison (依赖 Step 1)
  ── Step 3: 对比价格 ──
    Round 1: multi_platform_price_comparison (找到 5 个匹配)
    ✓ 数据有效，完成
[Phase 3] 综合分析结果...
```

存在三种推理模式：
- **ReAct**：`【Round N - Thought】` / `【Action】` / `【Observation】`
- **Plan-Execute**：Phase 1 计划 → Phase 2 执行（含 mini-ReAct）→ Phase 3 综合
- **Shopping（M5）**：状态机驱动，但**当前无任何可视化输出**

### 1.2 前端解析与渲染

`app.js:366-387` 的 `parseReasoningOutput()` 通过正则匹配 `Thought/思考`、`Action/调用工具`、`Observation/结果` 关键字将原始文本转为三种节点类型。

`renderTimeline()` 渲染垂直时间线：每个节点可展开/折叠，带灰色（思维）、品牌色（动作）、绿色（观察）圆点标记。

### 1.3 模拟步骤

`sendMessage()` 在请求发出后以 1.2 秒间隔渲染硬编码假步骤：
```
理解用户意图 → 规划执行策略 → 执行工具查询 → 获取查询结果
```
真实数据返回后，`parseReasoningOutput()` 覆盖这些假节点。

### 1.4 现有问题

| 问题 | 影响 | 严重度 |
|------|------|--------|
| 字符匹配解析脆弱 | `parseReasoningOutput` 依赖关键字，格式变动即失效 | 高 |
| 无实时流式传输 | 假步骤硬编码，真实推理延迟到达 | 高 |
| Plan-Execute 并行不可见 | 用户看不到哪些步骤并行执行 | 中 |
| M5 购物状态机不可见 | 槽位填充、阶段转换完全黑盒 | 中 |
| 无时间度量 | 无法判断瓶颈在哪个步骤 | 中 |
| 无模型路由信息 | 用户不知道各阶段用的什么模型 | 低 |
| 反思/重试无区分 | 空结果重试和正常调用混在一起 | 低 |

---

## 二、增强目标

### 2.1 总体目标

将推理过程从**被动文本捕获**升级为**主动结构化事件流**，使推理可视化从"事后日志"变为"实时可观测"。

### 2.2 分阶段目标

| 阶段 | 目标 | 工作量 |
|------|------|--------|
| **L1 — 结构化事件** | 后端用 `TraceEvent` 替代 `print()`，前端可靠解析 | 3-4h |
| **L2 — 实时流式** | SSE 推送事件，消除假步骤，推理实时可见 | 2-3h |
| **L3 — 模式可视化** | Plan-Execute DAG、M5 状态机、时间瀑布、模型路由 | 5-8h |
| **L4 — 调试仪表盘** | 追踪回放、A/B 对比、性能分析（远期） | 8-12h |

---

## 三、L1：结构化事件系统

### 3.1 后端事件模型

新增 `agent/trace.py`，定义结构化事件：

```python
from dataclasses import dataclass, field
from typing import Optional, List
import time

class EventType:
    INTENT           = "intent"            # 意图分类结果
    MODE_SELECT      = "mode_select"       # 路由到哪种执行模式
    PLAN_START       = "plan_start"        # Plan-Execute Phase 1 开始
    PLAN_GENERATED   = "plan_generated"    # LLM 生成计划完成（含 DAG 信息）
    STEP_START       = "step_start"        # 单个步骤开始
    STEP_END         = "step_end"          # 单个步骤结束（含结果摘要）
    TOOL_CALL        = "tool_call"         # 工具调用
    TOOL_RESULT      = "tool_result"       # 工具返回
    REFLECTION       = "reflection"        # 反思/重试决策
    REACT_ROUND      = "react_round"       # ReAct 单轮
    SYNTHESIZE_START = "synthesize_start"  # Phase 3 开始
    SYNTHESIZE_END   = "synthesize_end"    # Phase 3 完成
    SHOPPING_PHASE   = "shopping_phase"    # M5 状态机阶段
    SLOT_FILLED      = "slot_filled"       # M5 槽位填充
    ERROR            = "error"             # 错误/异常
    FINAL_ANSWER     = "final_answer"      # 最终回答

@dataclass
class TraceEvent:
    type: str
    data: dict
    ts: float = field(default_factory=time.time)
```

### 3.2 引擎改造

在 `ReActAgent` 中增加 `trace: List[TraceEvent]` 属性。各方法在关键节点 `self.trace.append(TraceEvent(...))`。

改动涉及：
- `run()` → 追加 intent、mode_select 事件
- `_react_loop()` → 每轮追加 react_round、tool_call、tool_result 事件
- `_generate_plan()` → 追加 plan_generated 事件（含 steps 依赖图）
- `_execute_plan()` → 每个 step 追加 step_start/step_end、tool_call/tool_result
- `_execute_step_with_react()` → mini-ReAct 各轮作为子事件
- `_synthesize()` → 追加 synthesize_start/end
- `_guided_shopping()` → 追加 shopping_phase、slot_filled
- `_build_reflection_message()` → 追加 reflection 事件

### 3.3 API 改造

`/api/chat` 端点返回结构化 `trace: List[dict]` 字段（替代原始文本 `reasoning`）：

```json
{
  "success": true,
  "session_id": "...",
  "answer": "...",
  "trace": [
    {"type": "intent", "data": {"intent": "comparison", "query": "..."}, "ts": 1716249600.123},
    {"type": "mode_select", "data": {"mode": "plan_execute"}, "ts": 1716249600.125},
    ...
  ]
}
```

向前兼容：保留 `reasoning` 字段（从 trace 事件拼接文本）。

### 3.4 前端改造

新增 `renderTrace()` 函数替代 `parseReasoningOutput()`：

```javascript
function renderTrace(events) {
    reasoningNodes = events.map(e => ({
        type: mapEventType(e.type),  // thought/action/observation/plan/error/slot
        title: buildTitle(e),
        detail: buildDetail(e),
        elapsedMs: e.ts ? elapsedFromStart(e.ts) : null,
    }));
    renderTimeline();
}
```

各事件类型映射为不同的视觉表现：
- `intent` / `mode_select` → 小标签而不是完整节点（如 `[意图：对比]` `[模式：Plan-Execute]`）
- `plan_generated` → 计划摘要节点（步数 + 并行组数）
- `step_start` / `step_end` → 步骤节点（含工具名 + 目的）
- `tool_result` → 结果摘要（找到？匹配数、最便宜价格）
- `shopping_phase` → 阶段转换节点
- `slot_filled` → 槽位填充节点
- `error` → 错误节点（红色高亮）

---

## 四、L2：SSE 实时流式传输

### 4.1 后端

新增 `/api/chat/stream` 端点，使用 Flask SSE：

```python
@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    def generate():
        agent.reset_trace()
        # 将 agent.trace 改为可迭代的 EventEmitter
        # 每个 trace.append 时 yield event
        for event in agent.run_stream(agent_message, history):
            yield f"data: {json.dumps(event)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'answer': answer})}\n\n"
    return Response(generate(), mimetype='text/event-stream')
```

引擎侧：将 `trace` 列表替换为 `EventEmitter`（可迭代），`append` 时触发 yield。

### 4.2 前端

```javascript
async function sendMessageStream() {
    const response = await fetch('/api/chat/stream', { method: 'POST', body: ... });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    clearReasoning();
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value);
        // 解析 SSE 事件
        const event = JSON.parse(extractSSEData(text));
        if (event.type === 'done') {
            addMessageToChat('assistant', event.answer);
        } else {
            addTraceEvent(event);  // 实时追加节点
        }
    }
}
```

效果：消除假步骤，节点随推理过程逐个出现。

---

## 五、L3：模式特定可视化

### 5.1 Plan-Execute DAG 视图

计划生成后，在时间线上方渲染一个**步骤依赖图**：

```
  [Step 1: semantic_product_search] ─────┐
                                          ├── [Step 3: 比价 #1]
  [Step 2: 查所有商品] ──────────────────┘
```

- 无依赖的步骤显示在并行组中（虚线框包围）
- 依赖箭头从 `$stepN` 引用源指向目标
- 执行完成的步骤变绿，失败的变红

### 5.2 时间瀑布

每个步骤显示耗时条形图（相对于总时间）：

```
Step 1: ████████░░ 2.3s
Step 2: ████░░░░░░ 1.1s（并行）
Step 3: ██████████ 3.0s
```

LLM 调用时间和工具执行时间用不同颜色区分。

### 5.3 M5 购物状态机

在推理面板顶部显示状态机横条：

```
[👋 问候] → [📋 填槽(2/3)] → [🔍 搜索] → [📊 推荐]
                               ↑ 当前阶段高亮
```

槽位填充进度：
```
预算: ✓ 5000  |  场景: ✓ 游戏  |  品牌: ? 待补充
```

### 5.4 模型路由指示器

每个阶段旁边显示模型标签：

```
[Phase 1 — 计划]  🏷 doubao-code
[Phase 2 — 执行]  🏷 doubao-pro
[Phase 3 — 综合]  🏷 doubao-pro
```

### 5.5 反思/重试可视化

反思节点用警告色渲染：

```
Step 2: multi_platform_price_comparison("华为Mate60")
  ├─ Round 1: 空结果 ⚠
  ├─ 💭 反思: 去掉颜色/内存过滤重试
  ├─ Round 2: 空结果 ⚠
  └─ ⚠ 未找到数据，返回空结果
```

---

## 六、L4：调试仪表盘（远期）

### 6.1 追踪回放

将完整 trace 序列化存储到 `eval/results/traces/`。前端提供回放器，可逐步骤播放历史推理过程。

### 6.2 A/B 对比

同一查询两次运行的结果并排对比：计划差异、工具选择差异、耗时差异。

### 6.3 性能分析

- LLM 调用总耗时 vs 工具执行总耗时
- 各步骤耗时分布饼图
- Token 用量统计（如果 API 返回）

---

## 七、实施顺序

```
L1 结构化事件  ──→  L2 SSE 流式  ──→  L3 模式可视化  ──→  L4 调试仪表盘
    (基础)           (体验)           (丰富度)            (远期)
```

L1 和 L2 是基础设施，完成后 L3 的各个子功能可独立并行开发。

---

## 八、兼容性与风险

- **向前兼容**：L1 保留 `reasoning` 文本字段，旧前端仍可工作
- **SSE 代理/网关兼容**：Flask SSE 在大多数反向代理下工作，但需确认 Nginx 未缓冲响应（可能需要 `proxy_buffering off`）
- **浏览器兼容**：`ReadableStream` 在所有现代浏览器中可用，IE 不支持（可接受）
- **测试覆盖**：每个 L 完成后运行 `eval/run.py` 确认回归
