# 下一代电商语义召回与 Agent 推荐 — 总规划

> 聚焦 IT3C 手机品类。基于现有 ReActAgent 架构迭代演进，拆解为 5 个可独立迭代的模块。
> 行业特异性收敛到 Config 层，执行通路跨行业复用。

---

## 一、现有架构回顾

```
app.py (Flask)
  │
  ├── initialize()
  │     ├── Settings()                    → config/settings.py
  │     ├── init_all_platforms()          → platforms/platform_database.py
  │     ├── init_parallel_agent()         → platforms/parallel_agent.py
  │     └── ReActAgent(...)               → agent/react_engine.py
  │           ├── tools=tool_registry.get_schemas()
  │           ├── tool_map=tool_registry.get_tool_map()
  │           └── config={model_react, model_plan, max_plan_steps, ...}
  │
  ├── POST /api/chat
  │     └── agent.run(query, history)
  │           ├── _detect_intent(query)    → recommendation / comparison / query
  │           ├── _react_loop(...)         → ReAct 标准循环
  │           └── _plan_and_execute(...)   → Plan-Execute 三阶段
  │
  └── tools/ (5 个，@register_tool)
        ├── multi_platform_price_comparison
        ├── query_single_platform_product
        ├── get_all_platform_products
        ├── search_product_by_image
        └── semantic_product_search        → 规则过滤 + hardcoded 排序
```

**关键约束：**

- Agent 入口 `run()` 的意图路由是稳定的，新增能力在路由之下展开
- 工具注册机制 `@register_tool` 是稳定的，新工具直接注册
- `config/settings.py` → `ReActAgent.__init__(config={...})` 的传参通道已有

---

## 二、模块总览

```
┌─────────────────────────────────────────────────────────────┐
│  Module 1: 行业配置框架（所有模块的基础依赖）                    │
│  config/industries/  →  Config Schema → 注入到各模块           │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┬───────────────┐
        ▼                ▼                ▼               ▼
┌───────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Module 2      │ │ Module 3     │ │ Module 4     │ │ Module 5     │
│ 语义召回升级   │ │ RAG 知识库   │ │ 生成式推荐    │ │ 引导式购物    │
│               │ │              │ │              │ │ Agent        │
│ 改: semantic_ │ │ 新增: rag_   │ │ 改: semantic_ │ │ 改: react_   │
│ search_tool   │ │ tool.py      │ │ search_tool   │ │ engine.py    │
│ 内部召回链路   │ │ 注册为第6工具 │ │ + prompt.py   │ │ 新增第4种模式 │
└──────┬────────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                 │                │                │
       └─────────────────┴────────────────┴────────────────┘
                                     │
                              ┌──────▼──────┐
                              │ 评估体系     │
                              │ 每模块自带   │
                              │ 专项评测     │
                              └─────────────┘
```

| 模块 | 改动核心文件 | 独立可测 | 依赖 | 状态 |
|------|------------|---------|------|:--:|
| M1: 行业配置框架 | `config/settings.py` + 新增 `config/industries/` | 是 | 无 | ✅ |
| M2: 语义召回升级 | `tools/semantic_search_tool.py` | 是 | M1 | ✅ |
| M3: RAG 知识库 | 新增 `tools/rag_tool.py` + `knowledge/` | 是 | M1 | ✅ 自研+BM25 |
| M4: 生成式推荐 | `tools/semantic_search_tool.py` + `agent/prompts.py` | 是 | M1, M2 | 📋 |
| M5: 引导式购物 Agent | `agent/react_engine.py` + `database/models.py` | 是 | M1 | ✅ |

**模块间关系**：M1 是所有模块的基础。M2/M3 完全独立可并行开发。M4 依赖 M2 的增强召回链路。M5 独立，调用的工具是 M2/M4 的输出。

---

## 三、各模块一句话 + 详情文档

- **M1: 行业配置框架** — 定义 Config Schema，实现手机品类首份配置，建立从 Settings 到各模块的 Config 注入通道 → [01-行业配置框架.md](modules/01-行业配置框架.md)
- **M2: 语义召回升级** — 在 `semantic_search_tool.py` 内部插入向量召回阶段，规则+向量混合检索，不改工具签名 → [02-语义召回升级.md](modules/02-语义召回升级.md)
- **M3: RAG 知识库** — 新增 `search_product_knowledge` 工具 + 手机领域知识库，Agent 可检索外部知识增强回答 → [03-RAG知识库.md](modules/03-RAG知识库.md)
- **M4: 生成式推荐** — LLM 意图分解 + LLM Rerank 替代 hardcoded 排序，推荐结果附带解释理由 → [04-生成式推荐.md](modules/04-生成式推荐.md)
- **M5: 引导式购物 Agent** — ShoppingContext 状态机 + 槽位填充，Agent 主动引导用户完成购物决策 → [05-引导式购物Agent.md](modules/05-引导式购物Agent.md)

---

## 四、落地路线图

### P0（M1 已完成，M2/M5 进行中）

| 模块 | 事项 | 改动文件 | 验证 | 状态 |
|------|------|---------|------|:--:|
| M1 | Config 注入通道 + 手机 Config | `config/settings.py`、`config/industries/mobile.py`（新） | 48 项测试全部通过 | ✅ |
| M2 | 向量召回 + 混合检索 | `tools/semantic_search_tool.py` | 24 项回归通过，向量召回 Top-5 有效 | ✅ |
| M5 | ShoppingContext + shopping 意图 | `agent/react_engine.py` | 33 项回归通过，购物对话 3 轮链路验证 | ✅ |

P0 全部完成。

### P1（M2 完成后）

| 模块 | 事项 | 改动文件 | 验证 |
|------|------|---------|------|
| M3 | RAG 工具 + 知识库 | `tools/rag_tool.py`（新）、`knowledge/mobile/`（新） | Precision@5 |
| M4 | LLM 意图分解 + Rerank | `tools/semantic_search_tool.py`、`agent/prompts.py` | Decompose Accuracy |

### P2（后续）

- M5 对比模式 + 完整购物链路
- 用户画像长期记忆
- 跨品类扩展（笔记本）

---

## 五、跨行业扩展

手机验证通过后，扩展到笔记本只需：

```
新增：
  config/industries/laptop.py     ← Config（Schema / 标签 / 权重 / 槽位 / Prompt）
  knowledge/laptop/               ← 笔记本知识库
  tests/eval_laptop/              ← 笔记本评测用例

小改：
  config/settings.py              ← 加一行 industry=laptop 的加载

不动：
  agent/react_engine.py           ← Agent 执行通路通用
  tools/semantic_search_tool.py   ← 召回引擎通用
  tools/rag_tool.py               ← RAG 检索器通用
  tools/registry.py               ← 工具注册通用
  app.py                          ← Flask 路由通用
```

---

## 六、基础设施需求

M2（语义召回）和 M3（RAG）需要 2 个新基础设施：Embedding 模型 + 向量存储。其余模块（M1/M4/M5）只需要现有 LLM API。

**mock 验证期最小方案**：复用火山引擎 ARK embedding + numpy 内存向量。只需 `pip install numpy`，不接入新服务。详见 → [00-基础设施评估.md](modules/00-基础设施评估.md)

---

## 七、模块文档索引

- [00: 基础设施评估](modules/00-基础设施评估.md) — Embedding模型、向量存储、知识文档等基础设施方案
- [Module 1: 行业配置框架](modules/01-行业配置框架.md)
- [Module 2: 语义召回升级](modules/02-语义召回升级.md)
- [Module 3: RAG 知识库](modules/03-RAG知识库.md)
- [Module 4: 生成式推荐](modules/04-生成式推荐.md)
- [Module 5: 引导式购物 Agent](modules/05-引导式购物Agent.md)
