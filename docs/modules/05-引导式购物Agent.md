# Module 5: 引导式购物 Agent

> 在 `ReActAgent.run()` 中新增第 4 种执行模式 "shopping"，通过 ShoppingContext 状态机实现槽位填充、主动引导、多轮跟进。
> 与现有的 recommendation / comparison / query 三种模式并列，不改动已有逻辑。
>
> **状态：已完成（2026-05-13）** — 33 项回归通过，购物对话 3 轮链路验证。
>
> **修订记录**：
> - 2026-05-13 v1.2: 实施完成。改动 agent/react_engine.py（ShoppingContext + _guided_shopping + 14 个新方法）

---

## 一、模块定位

### 1.1 要解决的问题

当前 Agent 完全被动：用户问什么就答什么，不会主动引导。

| 场景 | 当前行为 | 理想行为 |
|------|---------|---------|
| 用户说"想买个手机" | 无法触发合适模式，可能胡乱回答 | 追问"主要是打游戏、拍照还是日常用？" |
| 用户说"那小米14呢" | 靠滑动窗口理解指代，不可靠 | 从 ShoppingContext 中获取上一轮讨论的商品，精确消歧 |
| 用户说"这两个哪个值得买" | 同上，需要 LLM 猜"这两个"是什么 | 从对比篮中获取，精确对比 |
| 用户推荐后说"再加1000预算呢" | 重新搜、重新排序、重新回答 | 更新 slot budget_max，增量搜索，只展示差异 |
| 用户推荐后说"有没有便宜点的" | 同上 | 调整 budget_max 或 sort_by，重新推荐 |

**根本原因**：没有结构化的购物状态追踪。每一轮都是独立的 ReAct 循环，上下文只靠滑动窗口在 prompt 里堆历史消息。

### 1.2 目标

在 `ReActAgent` 中新增 `_guided_shopping()` 方法，通过 `ShoppingContext` 状态机追踪多轮购物对话：

```
GREETING → SLOT_FILLING → SEARCHING → RECOMMENDING → FOLLOW_UP
                                                  → COMPARING → FOLLOW_UP
```

### 1.3 不改什么

- `_react_loop()` — 标准 ReAct 模式不改
- `_plan_and_execute()` — Plan-Execute 模式不改
- `_detect_intent()` 的现有三类分类 — 只在末尾追加 shopping 判断
- 工具层 — 调用的还是现有工具
- 前端 `/api/chat` 接口

---

## 二、方案设计

### 2.1 意图路由扩展

在 `_detect_intent()` 末尾、return "query" 之前，新增 shopping 判断：

```python
def _detect_intent(self, query: str) -> str:
    # ... 现有逻辑：recommendation / comparison 判断 ...
    
    # ── 新增：shopping 意图检测 ──
    # 条件：无明确型号 + 无场景触发词 + 无对比证据 + 有购物意图
    shopping_keywords = ["买", "想买", "想换", "换个", "挑", "选", "帮我推荐"]
    has_shopping_intent = any(w in query for w in shopping_keywords)
    has_model = self._count_models(query) >= 1
    
    if has_shopping_intent and not has_model:
        # 有购物意图但没说具体型号 → 进入引导式购物
        # 但如果有场景/预算触发词，优先走 recommendation
        has_scene = any(kw in query for kw in USE_CASE_TRIGGER_MAP)
        has_budget = any(w in query for w in ["以内", "以下", "预算"])
        if not has_scene and not has_budget:
            return "shopping"
    
    # ... 现有逻辑继续 ...
    return "query"
```

**shopping 触发条件总结**：
- 有购物意图词（"买""想买""推荐"）
- 无明确型号（"iPhone 15"不触发）
- 无场景关键词（"游戏""拍照"不触发，那些走 recommendation）
- 无预算表述（"5000以内"不触发，走 recommendation）
- 典型触发 query："想买个手机"、"帮我挑一款"、"想换个新手机不知道买什么"

### 2.2 `run()` 路由扩展

```python
def run(self, user_query, history=None, verbose=True):
    if history:
        history = self._slide_window(history)
    
    intent = self._detect_intent(user_query)
    
    if intent == "recommendation":
        return self._react_loop(user_query, history, verbose, intent_hint="recommendation")
    
    elif intent == "comparison":
        return self._plan_and_execute(user_query, history, verbose)
    
    elif intent == "shopping":                                    # ← 新增
        if verbose:
            print(f"\n[Intent: shopping] 启用引导式购物模式")
        return self._guided_shopping(user_query, history, verbose)
    
    else:  # query
        return self._react_loop(user_query, history, verbose)
```

### 2.3 ShoppingContext 状态机

#### 2.3.1 数据结构

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class ShoppingContext:
    """购物上下文 — 跨多轮持久化（ReActAgent 实例属性）"""
    
    phase: str = "greeting"          # greeting | slot_filling | searching | recommending | comparing | follow_up
    slots: Dict[str, any] = field(default_factory=dict)
    candidates: List[Dict] = field(default_factory=list)
    compare_basket: List[Dict] = field(default_factory=list)
    question_count: int = 0
    last_recommendation: Optional[Dict] = None
    
    def reset(self):
        """重置上下文（新购物会话开始时调用）"""
        self.phase = "greeting"
        self.slots.clear()
        self.candidates.clear()
        self.compare_basket.clear()
        self.question_count = 0
        self.last_recommendation = None
    
    def add_slot(self, key: str, value):
        """更新槽位，相同 key 覆盖"""
        self.slots[key] = value
    
    def get_missing_required(self, slot_defs: list) -> list:
        """返回缺失的必填槽位定义列表"""
        missing = []
        for slot_def in slot_defs:
            if slot_def.get("required") and slot_def["name"] not in self.slots:
                missing.append(slot_def)
        return missing
```

在 `ReActAgent.__init__()` 中初始化：

```python
self.shopping_context = ShoppingContext()
```

#### 2.3.2 状态转移

```
┌──────────┐
│ GREETING │  ← 初始状态
└────┬─────┘
     │ 首次进入 shopping
     ▼
┌──────────────┐
│ SLOT_FILLING │  ← 追问关键槽位
└──────┬───────┘
       │ 关键槽位已填充 或 question_count ≥ max
       ▼
┌───────────┐
│ SEARCHING │  ← 调 semantic_product_search
└─────┬─────┘
      │ 成功返回结果
      ▼
┌───────────────┐
│ RECOMMENDING  │  ← 展示推荐 + 等待用户反馈
└───┬───────┬───┘
    │       │
    │       │ 用户说"这两个哪个好"/"对比"
    │       ▼
    │   ┌───────────┐
    │   │ COMPARING │  ← 进入对比模式
    │   └─────┬─────┘
    │         │ 对比完成
    │         ▼
    │   ┌───────────┐
    │   │ FOLLOW_UP │  ← 等待用户下一个操作
    │   └─────┬─────┘
    │         │
    ▼         ▼
┌───────────┐
│ FOLLOW_UP │  ← 用户追加条件/切换商品/结束
└─────┬─────┘
      │
      │ 用户说"再加预算"/"便宜点"/"换一个" → 更新 slot → SEARCHING
      │ 用户说"那XX呢" → 更新关注商品 → SEARCHING
      │ 用户说"谢谢"/"就这个" → 结束
      │ 用户问无关问题 → 退出 shopping，走正常 ReAct
```

### 2.4 `_guided_shopping()` 主流程

```python
def _guided_shopping(
    self,
    user_query: str,
    history: Optional[List[Dict]],
    verbose: bool,
) -> str:
    """引导式购物主流程"""
    
    slots_cfg = self.industry_config.get("shopping_slots", [])
    max_questions = self.industry_config.get("max_slot_questions", 3)
    
    ctx = self.shopping_context
    
    # ── Phase: GREETING ──
    if ctx.phase == "greeting":
        ctx.phase = "slot_filling"
        # 从历史对话注入上下文（指代消歧）
        self._inject_from_history(history, slots_cfg)
        # 从首轮 query 中提取已知信息
        self._extract_slots_from_query(user_query, slots_cfg)
        
        # 如果首轮已给出足够信息，直接进入搜索
        missing = ctx.get_missing_required(slots_cfg)
        if not missing:
            ctx.phase = "searching"
        else:
            # 打招呼 + 问第一个关键问题
            return self._greet_and_ask(missing, slots_cfg)
    
    # ── Phase: SLOT_FILLING ──
    if ctx.phase == "slot_filling":
        # 从本轮回答中提取新信息
        self._extract_slots_from_query(user_query, slots_cfg)
        ctx.question_count += 1
        
        missing = ctx.get_missing_required(slots_cfg)
        
        # 情况 A：关键槽位已补齐 → 搜索
        if not missing:
            ctx.phase = "searching"
        
        # 情况 B：追问次数用尽 → 用现有信息搜索
        elif ctx.question_count >= max_questions:
            ctx.phase = "searching"
        
        # 情况 C：还有可追问的非必填槽位 → 继续问
        else:
            optional_missing = [
                s for s in slots_cfg
                if not s.get("required") and s["name"] not in ctx.slots
            ]
            if optional_missing:
                next_slot = optional_missing[0]
                return self._ask_slot_question(next_slot)
            else:
                ctx.phase = "searching"
    
    # ── Phase: SEARCHING ──
    if ctx.phase == "searching":
        result = self._search_with_slots(ctx.slots)
        ctx.candidates = result.get("recommendations", [])
        ctx.phase = "recommending"
        ctx.last_recommendation = result
        return self._format_recommendation(result)
    
    # ── Phase: RECOMMENDING / COMPARING / FOLLOW_UP ──
    if ctx.phase in ("recommending", "comparing", "follow_up"):
        return self._handle_followup(user_query)
    
    # 兜底
    return self._react_loop(user_query, history, verbose)


def _extract_slots_from_query(self, query: str, slots_cfg: list):
    """从用户输入中提取槽位信息，更新 ShoppingContext"""
    ctx = self.shopping_context
    
    for slot_def in slots_cfg:
        name = slot_def["name"]
        if name in ctx.slots:
            continue  # 已填充，跳过
        
        # 策略 1：关键词匹配（extract_keywords 为 dict 时做值映射，list 时做存在检测）
        keywords = slot_def.get("extract_keywords")
        if isinstance(keywords, dict):
            for kw, mapped_value in keywords.items():
                if kw in query:
                    ctx.add_slot(name, mapped_value)
                    break
        elif isinstance(keywords, list):
            for kw in keywords:
                if kw in query:
                    ctx.add_slot(name, kw)
                    break
        
        # 策略 2：正则提取（如金额）
        pattern = slot_def.get("extract_pattern")
        if pattern and name not in ctx.slots:
            import re
            m = re.search(pattern, query)
            if m:
                value = m.group(1)
                ctx.add_slot(name, int(value))
    
    # 特殊处理：budget_range 提取后映射到 budget_max
    if "budget_range" in ctx.slots and "budget_max" not in ctx.slots:
        val = ctx.slots.pop("budget_range")
        ctx.add_slot("budget_max", val)


def _search_with_slots(self, slots: dict) -> dict:
    """将槽位转换为 semantic_product_search 参数并调用"""
    from tools.semantic_search_tool import semantic_product_search
    
    params = {}
    if "primary_use_case" in slots:
        params["use_case"] = slots["primary_use_case"]
    if "budget_max" in slots:
        params["budget_max"] = slots["budget_max"]
    if "brand_preference" in slots:
        params["brand"] = slots["brand_preference"]
    if "processor_preference" in slots:
        proc_map = self.industry_config.get("processor_normalize", {})
        pref = slots["processor_preference"]
        params["processor_brand"] = proc_map.get(pref, pref)

    params.setdefault("category", self.industry_config.get("category", "手机"))
    result = semantic_product_search(**params)
    return result
```

### 2.5 辅助方法实现

以下方法在上文 `_guided_shopping()` 中被调用，在此补充完整实现。

```python
def _greet_and_ask(self, missing: list, slots_cfg: list) -> str:
    """打招呼 + 追问第一个缺失的必填槽位"""
    first_missing = missing[0]
    question = first_missing.get("question", "")
    options = first_missing.get("options", [])
    
    lines = ["您好！让我帮您挑选合适的手机。"]
    if question:
        lines.append(question)
    if options:
        lines.append("可选：" + " / ".join(options))
    return "\n".join(lines)


def _ask_slot_question(self, slot_def: dict) -> str:
    """追问单个槽位"""
    question = slot_def.get("question", "")
    options = slot_def.get("options", [])
    
    parts = [question]
    if options:
        parts.append("可选：" + " / ".join(options))
    return " ".join(parts)


def _search_and_respond(self) -> str:
    """执行搜索并格式化推荐返回"""
    ctx = self.shopping_context
    result = self._search_with_slots(ctx.slots)
    ctx.candidates = result.get("recommendations", [])
    ctx.last_recommendation = result
    return self._format_recommendation(result)


def _format_recommendation(self, result: dict) -> str:
    """将推荐结果格式化为用户可读文本"""
    recs = result.get("recommendations", [])
    if not recs:
        return "抱歉，没有找到符合条件的商品。要不要调整一下条件试试？"

    lines = ["为您找到以下商品：", ""]
    for r in recs[:5]:
        rank = r.get("rank", "?")
        name = r.get("product_name", "")
        price = r.get("price", "?")
        platform = r.get("platform", "")
        proc = r.get("processor", "")
        desc = r.get("description", "")
        lines.append(f"{rank}. {name}")
        lines.append(f"   ¥{price} | {platform} | {proc}")
        if desc:
            lines.append(f"   {desc}")
        lines.append("")
    
    total = result.get("total_found", len(recs))
    lines.append(f"共找到 {total} 款商品。您可以说'对比前两个'、'有没有便宜点的'继续筛选。")
    return "\n".join(lines)


def _format_compare_table(self, products: list, dimensions: list) -> str:
    """将对比篮中的商品格式化为 LLM 可读对比文本"""
    lines = []
    for i, p in enumerate(products):
        lines.append(f"[{i+1}] {p.get('product_name','')} — ¥{p.get('price','')}")
        for d in dimensions:
            key = d["key"]
            value = p.get(key, "—")
            lines.append(f"    {d['name']}: {value}")
        lines.append("")
    return "\n".join(lines)


def _detect_budget_adjust(self, query: str):
    """从用户输入中提取新的预算值。返回 None 表示未检测到。"""
    import re
    patterns = [
        r"再加\s*(\d+)",       # "再加 1000"
        r"预算.*?(\d+)",       # "预算提高到 6000"
        r"(\d+)\s*以内",       # "6000 以内"
        r"降到\s*(\d+)",       # "降到 4000"
    ]
    for pat in patterns:
        m = re.search(pat, query)
        if m:
            return int(m.group(1))
    return None


def _detect_product_switch(self, query: str):
    """检测用户是否在切换关注的商品。返回商品名或 None。"""
    ctx = self.shopping_context
    # 匹配 "那XX呢" 模式
    import re
    m = re.search(r"那[个款]?\s*(\S+?)\s*(?:呢|怎么样|如何)", query)
    if m:
        return m.group(1)
    # 匹配已知候选商品名
    for c in ctx.candidates:
        name = c.get("product_name", "")
        if name in query:
            return name
    return None
```

### 2.6 中途退出与话题切换策略

购物模式本质上在 Agent 的 `run()` 请求-响应循环中运行。每轮对话独立调用 `run()`，ShoppingContext 的 phase 状态跨轮保持。

**退出条件**（触发后 context 自动 reset）：
1. 用户说"谢谢"、"好的"、"就这个"、"下单"、"买了" → 自然结束
2. `_detect_intent()` 检测到用户问了明确型号的查询（如"iPhone 15 多少钱"）→ 退出 shopping，回到正常 query 模式
3. 调用 `self._react_loop()` 兜底时 → context 保持，但如果用户连续两轮不触发 shopping 意图，则自动 reset

**实现方式**：在 `run()` 的 shopping 分支外新增一段前处理：

```python
def run(self, user_query, history=None, verbose=True):
    if history:
        history = self._slide_window(history)
    
    intent = self._detect_intent(user_query)
    
    # 如果当前在购物模式中，但本轮意图不是 shopping
    if self.shopping_context.phase != "greeting" and intent != "shopping":
        # 检测是否彻底退出购物
        if self._is_ending_shopping(user_query):
            self.shopping_context.reset()
        # 否则保持 context，但不走 shopping 流程
    
    # ... 原有路由 ...
```

### 2.7 history 参数利用

在 GREETING 阶段，从 `history` 中提取有用信息注入初始槽位：

```python
def _inject_from_history(self, history: list, slots_cfg: list):
    """从历史对话中提取上下文注入槽位，解决'那'、'这个'等指代消歧"""
    if not history:
        return
    # 取最近 3 轮用户消息拼接，跑一遍 extract
    recent_text = " ".join(
        h.get("content", "") for h in history[-6:] if h.get("role") == "user"
    )
    if recent_text:
        self._extract_slots_from_query(recent_text, slots_cfg)
```

### 2.8 FOLLOW_UP 处理

```python
def _handle_followup(self, user_query: str) -> str:
    """处理推荐后的用户跟进"""
    ctx = self.shopping_context
    
    # 检测对比意图
    if any(w in user_query for w in ["对比", "比较", "哪个好", "哪个更", "这两个"]):
        ctx.phase = "comparing"
        return self._handle_comparison(user_query)
    
    # 检测预算调整
    budget_adjust = self._detect_budget_adjust(user_query)
    if budget_adjust:
        ctx.slots["budget_max"] = budget_adjust
        ctx.phase = "searching"
        return self._search_and_respond()
    
    # 检测价格敏感（"便宜点"、"有没有更便宜的"）
    if any(w in user_query for w in ["便宜", "更便宜", "贵了", "超预算"]):
        ctx.slots["sort_by"] = "price"
        ctx.phase = "searching"
        return self._search_and_respond()
    
    # 检测商品切换（"那XX呢"）
    new_product = self._detect_product_switch(user_query)
    if new_product:
        ctx.slots["focus_product"] = new_product
        ctx.phase = "comparing"
        return self._handle_product_switch(new_product)
    
    # 检测结束
    if any(w in user_query for w in ["谢谢", "好的", "就这个", "下单", "买了"]):
        ctx.reset()
        return "好的！如果还有其他需要，随时告诉我。"
    
    # 默认：当作新条件追加，重新搜
    self._extract_slots_from_query(user_query, self.industry_config.get("shopping_slots", []))
    ctx.phase = "searching"
    return self._search_and_respond()
```

### 2.9 对比模式（COMPARING）

```python
def _handle_comparison(self, user_query: str) -> str:
    """对比模式：将对比篮中的商品按维度逐项对比"""
    ctx = self.shopping_context
    dimensions = self.industry_config.get("compare_dimensions", [])
    
    # 如果对比篮为空，尝试从 candidates 中提取
    if not ctx.compare_basket:
        # 从当前推荐中选前 2-3 个
        ctx.compare_basket = ctx.candidates[:3]
    
    if not ctx.compare_basket:
        return "目前还没有可以对比的商品，先让我帮您搜一下吧。"
    
    # 构建对比 prompt
    compare_text = _format_compare_table(ctx.compare_basket, dimensions)
    
    # 如果有 RAG，检索额外知识
    rag_context = ""
    if self.industry_config.get("enable_rag"):
        try:
            from tools.rag_tool import search_product_knowledge
            product_names = [p["product_name"] for p in ctx.compare_basket]
            rag_result = search_product_knowledge(
                query=f"{' vs '.join(product_names)} 对比评测",
                knowledge_type="phone_review",
                top_k=3,
            )
            refs = rag_result.get("references", [])
            if refs:
                rag_context = "\n\n## 相关知识库参考\n" + "\n".join(
                    f"- [{r['source']}] {r['content'][:300]}" for r in refs
                )
        except Exception:
            pass
    
    messages = [
        {"role": "system", "content": "你是手机对比专家。根据用户需求和参数逐项对比。"},
        {"role": "user", "content": f"""用户想对比以下商品：

{compare_text}
{rag_context}

请从以下维度逐项对比并给出最终建议：""" + "\n".join(
    f"- {d['name']}（权重 {d['weight']*100:.0f}%）" for d in dimensions
)},
    ]
    
    resp = self.client.chat.completions.create(
        model=self.model_synthesize,
        messages=messages,
        temperature=0.3,
        max_tokens=1200,
    )
    
    ctx.phase = "follow_up"
    return resp.choices[0].message.content
```

---

## 三、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `agent/react_engine.py` | 修改 | `_detect_intent()` 新增 shopping 分类；`run()` 新增 shopping 路由；新增 `_guided_shopping()`、`_extract_slots_from_query()`、`_handle_followup()`、`_handle_comparison()` 等方法；`__init__()` 初始化 `ShoppingContext` |
| `config/industries/mobile.py` | 依赖 | `shopping_slots`、`max_slot_questions`、`compare_dimensions`（M1 已定义） |

**不改的文件**：
- `agent/prompts.py` — shopping 模式有独立的 prompt 逻辑，不加到 system prompt
- 所有 `tools/` — 调的还是现有工具
- `app.py` — 接口不变
- 前端 — 对话接口不变

---

## 四、测试方案

### 4.1 单轮功能测试

| 测试项 | 输入 | 期望输出 |
|--------|------|---------|
| 首次进入 | "想买个手机" | 追问使用场景 |
| 补充场景 | "打游戏" | 追问预算 |
| 补充预算 | "5000 左右" | 搜索并推荐 |
| 信息充分时直达 | "想买个游戏手机 5000 左右" | 直接搜索推荐（不追问） |

### 4.2 多轮对话测试

模拟完整购物链路：

```
轮1: 用户 "想买个手机"
     Agent 应追问使用场景

轮2: 用户 "主要是打游戏"
     Agent 应追问预算

轮3: 用户 "5000 以内"
     Agent 应搜索并展示推荐

轮4: 用户 "这两个哪个好"（上下文：上一轮的 top-2）
     Agent 应识别对比意图，进入 COMPARING，逐项对比

轮5: 用户 "那第三个便宜的那个呢"
     Agent 应定位到第 3 个推荐商品
```

评估指标：
- **Task Completion Rate**：完整链路走完（从需求到推荐）的比例
- **Avg Turns to Decision**：平均几轮对话给出推荐
- **Slot Extraction Accuracy**：从对话中提取槽位的准确率
- **Question Relevance**：Agent 追问是否合理（不重复、不跳跃）

### 4.3 退化测试

| 测试项 | 说明 |
|--------|------|
| 非购物 query 不受影响 | "iPhone 15 多少钱" 仍然走 query 模式 |
| 推荐型 query 不受影响 | "推荐游戏手机" 仍然走 recommendation 模式 |
| Context 隔离 | 购物结束后 context 重置，不影响后续对话 |

### 4.4 测试文件

```
tests/
  eval_m5_shopping/
    __init__.py
    test_slot_extraction.py      ← 槽位提取准确率
    test_dialogue_flow.py        ← 多轮对话模拟
    test_regression.py           ← 现有模式不受影响
```

---

## 五、验收标准

- [ ] "想买个手机" → 触发 shopping 模式，追问使用场景
- [ ] 追问最多 3 个问题后强制搜索
- [ ] 关键槽位（primary_use_case）补齐后立即搜索
- [ ] "这两个哪个好" → 正确识别对比意图，进入 COMPARING
- [ ] "再加 1000 预算" → 正确更新 budget 并重新推荐
- [ ] 现有 P2 E2E 测试全部通过（normal query 不受影响）
- [ ] Context 在购物对话自然结束或用户切换话题时正确重置

---

## 六、依赖

```
M1: 行业配置框架 → shopping_slots, max_slot_questions, compare_dimensions
```

M5 独立于 M2/M3/M4。shopping 模式调用的 `semantic_product_search` 是现有版本，后续 M2/M4 增强后自动受益。
