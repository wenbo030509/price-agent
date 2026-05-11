# Plan-Execute 策略方案

## 一、当前处理逻辑

### 1.1 简单 query 的流程

```
用户："iPhone 15 最便宜的平台"
  → Round 1: Thought → Action: multi_platform_price_comparison("iPhone 15")
  → Round 2: Thought → Final Answer: "拼多多 ¥5750"
```

路径：1 次 LLM 推理 → 1 次工具调用 → 1 次 LLM 合成。高效。

### 1.2 复杂 query 的流程

```
用户："对比 iPhone 15 和小米14 在京东和淘宝的价格，分析哪个更值得买"

  → Round 1: Thought → Action: multi_platform_price_comparison("iPhone 15")
      拿到 iPhone 15 全部平台价格（但用户只要京东和淘宝）

  → Round 2: Thought → Action: multi_platform_price_comparison("小米14")
      拿到小米14 全部平台价格

  → Round 3: Thought → Action: query_single_platform_product("jd", "iPhone 15")
      LLM 发现上一轮拿到的数据不够精确，又回头查

  → Round 4: Thought → Final Answer（或 max_round 耗尽）
```

问题：

| 问题 | 后果 |
|------|------|
| **串行执行** | 4 个工具调用 = 4 轮 LLM + 4 轮等待，总耗时 = 各轮之和 |
| **无规划** | LLM 每轮"摸着石头过河"，可能选错工具、漏查平台 |
| **浪费轮次** | round 1 查了全部平台，round 3 发现需要更精确的查询，round 1 白费 |
| **max_round 瓶颈** | 复杂 query 需要 5+ 轮，当前 max_round=5 可能不够 |
| **工具调用冗余** | 没有判断依赖关系，本该并行的查询被串行化了 |

---

## 二、Plan-Execute 策略设计

### 2.1 核心思想

从"摸着石头过河"改为"先画地图再走路"：

```
传统 ReAct：  Think → Act → Observe → Think → Act → Observe → ...

Plan-Execute： Plan → [Execute*N 并行] → Synthesize
```

### 2.2 两阶段流程

```
用户 query
    │
    ▼
┌──────────────────────────────────────┐
│ Phase 1: PLAN（1 次 LLM 调用）        │
│                                      │
│ 分析 query，输出执行计划：              │
│ {                                    │
│   "complexity": "simple|complex",    │
│   "plan": [                          │
│     {                                │
│       "step": 1,                     │
│       "tool": "xxx",                 │
│       "args": {...},                 │
│       "depends_on": null,            │
│       "purpose": "查询 iPhone 15 价格"│
│     },                               │
│     {                                │
│       "step": 2,                     │
│       "tool": "xxx",                 │
│       "args": {...},                 │
│       "depends_on": null,  // 无依赖 │
│       "purpose": "查询小米14 价格"     │
│     }                                │
│   ]                                  │
│ }                                    │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ Phase 2: EXECUTE                     │
│                                      │
│ 识别依赖关系，分组并行执行：            │
│                                      │
│ Group 1（无依赖，并行）：               │
│   ├── Thread: multi_platform_compare  │
│   └── Thread: multi_platform_compare  │
│                                      │
│ Group 2（依赖 Group 1 结果，串行）：    │
│   └── query_single_platform          │
│                                      │
│ 收集所有 observation                  │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ Phase 3: SYNTHESIZE（1 次 LLM 调用）  │
│                                      │
│ 将所有 observation 注入 LLM，          │
│ 令其综合分析并生成 Final Answer        │
└──────────────────────────────────────┘
```

### 2.3 触发条件：复杂度判断

不是所有 query 都需要 Plan-Execute。简单 query 走传统 ReAct 更快。

```python
COMPLEXITY_KEYWORDS = [
    # 多商品
    "对比", "比较", "vs", "和", "与", "以及",
    # 多维分析
    "分析", "推荐", "建议", "哪个更", "怎么选",
    # 条件组合
    "并且", "同时", "还要", "另外",
]

def is_complex(query: str) -> bool:
    """判断是否需要走 Plan-Execute"""
    # 规则1: 包含多个商品名
    product_count = count_product_names(query)  # 匹配已知商品名列表
    if product_count >= 2:
        return True

    # 规则2: 包含复杂度关键词
    if any(kw in query for kw in COMPLEXITY_KEYWORDS):
        return True

    # 规则3: LLM 自判断（最准确但多一次调用）
    # 可由 Phase 1 的 plan prompt 直接判断 complexity

    return False
```

更可靠的方式：让 Phase 1 的 LLM 调用自己判断 `complexity`。simple → 走传统 ReAct；complex → 输出 plan。

---

## 三、实现方案

### 3.1 新增 Plan-Execute Agent

```python
# agent/plan_execute_engine.py

class PlanExecuteAgent:
    """Plan-Execute 推理引擎"""

    def __init__(self, client, model, tools, tool_map, max_plan_steps=8):
        self.client = client
        self.model = model
        self.tools = tools
        self.tool_map = tool_map
        self.max_plan_steps = max_plan_steps

    def run(self, user_query: str, history=None) -> str:
        # Phase 1: Plan
        plan = self._plan(user_query, history)

        if plan["complexity"] == "simple":
            # 简单 query → 回退到传统 ReAct
            return self._react_fallback(user_query, history)

        # Phase 2: Execute
        observations = self._execute(plan["steps"])

        # Phase 3: Synthesize
        return self._synthesize(user_query, plan, observations)
```

### 3.2 Phase 1 Prompt 设计

```python
PLAN_SYSTEM_PROMPT = """你是一个任务规划器。分析用户 query，输出执行计划。

## 可用工具
{tools_description}

## 输出格式
{{
  "complexity": "simple|complex",
  "reasoning": "为什么是 simple/complex",
  "plan": [
    {{
      "step": 1,
      "tool": "工具名称",
      "args": {{"参数名": "参数值"}},
      "depends_on": null,
      "purpose": "这一步的目的"
    }}
  ]
}}

## 规划原则
1. 依赖关系：如果 step B 的结果依赖 step A 的输出，标记 depends_on
2. 并行机会：没有依赖的 step 可以并行执行，放在同一 level
3. 最小化：能用 1 个工具完成的不要用 2 个
4. simple 判断：只需 1 个工具且无需复杂分析 → simple
"""
```

### 3.3 Phase 2 依赖图执行

```python
def _execute(self, steps: List[Dict]) -> Dict[int, Dict]:
    """按依赖关系分组并行执行"""
    from collections import defaultdict

    # 构建依赖图
    levels = defaultdict(list)
    for step in steps:
        dep = step.get("depends_on")
        if dep is None:
            levels[0].append(step)
        else:
            levels[dep + 1].append(step)

    results = {}

    for level in sorted(levels.keys()):
        batch = levels[level]

        if len(batch) == 1:
            # 单工具，直接执行
            step = batch[0]
            results[step["step"]] = self._call_tool(step["tool"], step["args"])
        else:
            # 多工具，并行执行
            results.update(self._call_tools_parallel(batch))

    return results
```

### 3.4 与现有 ReActAgent 的关系

```
agent.run()
    │
    ├── 复杂度判断
    │     │
    │     ├── simple → 传统 ReAct 循环（现有逻辑）
    │     │
    │     └── complex → PlanExecuteAgent
    │           ├── Phase 1: Plan (1 LLM call)
    │           ├── Phase 2: Execute (并行工具调用)
    │           └── Phase 3: Synthesize (1 LLM call)
```

可以做成 `ReActAgent.run()` 的一个分支，不需要修改现有 API：

```python
def run(self, user_query, history=None, verbose=True):
    # 先判断复杂度
    if self._needs_plan(user_query):
        return self._plan_execute(user_query, history, verbose)

    # 否则走传统 ReAct
    return self._react_loop(user_query, history, verbose)
```

---

## 四、收益分析

### 4.1 性能对比（以"对比 iPhone 15 和小米14"为例）

| 指标 | 当前 ReAct | Plan-Execute | 提升 |
|------|-----------|-------------|------|
| LLM 调用次数 | 3-5 次 | 2 次（plan + synthesize） | **40-60% 减少** |
| 总耗时 | 15-30s | 5-8s | **60-70% 减少** |
| 工具执行 | 串行 2-3 轮 | 并行 1 批 | **2-3x 加速** |
| max_round 风险 | 可能耗尽 | 固定 2 轮 | 不会超限 |

### 4.2 质量提升

| 维度 | 当前 | Plan-Execute |
|------|------|-------------|
| 工具选择准确率 | 依赖单轮 LLM 判断 | 一次性规划，上下文充分 |
| 漏查率 | 可能漏掉需要的查询 | 显式 plan，可审计 |
| 复现性 | 非确定性 ReAct 循环 | 确定的 plan → execute 流程 |

### 4.3 成本

| 指标 | 当前 | Plan-Execute |
|------|------|-------------|
| LLM token 消耗 | 每轮 system + history + tool_results | Plan prompt 更长，但轮次少 |
| 简单 query | 1-2 轮 LLM | 1-2 轮（不变，simple 回退） |
| 复杂 query | 3-5 轮 LLM | 2 轮 LLM（净减少） |

---

## 五、风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| Plan 不正确（规划了错误的工具） | Phase 3 的 LLM 看到实际结果后会纠正；加入 plan validation |
| 依赖关系判断错误 | `depends_on` 可选字段，不填默认并行；LLM 会保守填串行 |
| Plan prompt 过长（罗列所有工具 schema） | 已有工具只有 3 个，prompt 可控 |
| 简单 query 被误判为 complex | `complexity: simple` 回退机制 |
| 复杂 query 被误判为 simple | Phase 1 prompt 明确教 LLM 判断标准 |

---

## 六、分步实施建议

### Step 1：最小可行版（1-2 小时）

只实现 Phase 1 Plan + Phase 2 并行执行，暂不做依赖图：

```python
# agent/react_engine.py 新增方法
def _plan_and_execute(self, user_query, history):
    plan_prompt = self._build_plan_prompt(user_query, history)
    plan_resp = self.client.chat.completions.create(
        model=self.model,
        messages=[{"role": "user", "content": plan_prompt}],
        response_format={"type": "json_object"},
    )
    plan = json.loads(plan_resp.choices[0].message.content)

    if plan.get("complexity") == "simple":
        return None  # 回退到传统 ReAct

    # 并行执行所有 step
    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for step in plan["plan"]:
            f = executor.submit(
                self.tool_map[step["tool"]], **step["args"]
            )
            futures[f] = step["step"]
        for f in as_completed(futures):
            step_num = futures[f]
            results[step_num] = f.result()

    # Synthesize
    return self._synthesize(user_query, plan, results)
```

### Step 2：依赖图（1 小时）

加入 `depends_on` 支持，分 level 串行执行。

### Step 3：复杂度自适应（30 分钟）

把 plan prompt 中的 complexity 判断逻辑精细化。

---

## 七、替代方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| **传统 ReAct**（当前） | 简单、灵活 | 慢、无规划 | 简单单步查询 |
| **Plan-Execute**（建议） | 快、可并行、可审计 | plan 可能错 | 复杂多步查询 |
| **ReAct + 多工具并行** | 不改流程，只加并行 | 仍然串行多轮 | 单轮多工具场景 |
| **ReWOO**（Reasoning WithOut Observation） | 极快（1 次 LLM） | 不纠错 | 确定性强的场景 |

建议：**Plan-Execute + 简单 query 回退 ReAct**，结合两者优势。
