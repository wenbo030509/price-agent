# Price Agent — 智能识物比价 AI 助手

基于 **ReAct + Plan-Execute 混合策略**的 LLM Agent，支持文本查询和图片识物两种入口，在京东、淘宝、拼多多、苏宁 4 个电商平台并行比价，并具备**语义推荐**、**引导式购物**、**RAG 知识增强**能力。

> 当前为 mock 数据验证版本。架构上预留了 DataSource 抽象层，验证通过后可替换为真实电商数据源。

## 核心架构

```
用户输入（文本 / 图片）
        │
        ▼
┌─────────────────────────────────────────────────┐
│              ReActAgent 引擎                      │
│                                                   │
│  _detect_intent() → 意图分类                       │
│       │              │              │             │
│       ▼              ▼              ▼             │
│  recommendation  comparison    shopping 🆕       │
│  (语义推荐)     (Plan-Execute) (引导式购物)        │
│       │              │              │             │
│       ▼              ▼              ▼             │
│  _react_loop   _plan_and_     _guided_shopping   │
│  +intent_hint  execute()      + ShoppingContext  │
│       │         Phase 1: Plan       │            │
│       │         Phase 2: mini-ReAct │            │
│       │         Phase 3: Synthesize │            │
│       │              │              │             │
│       └──────┬───────┴──────┬───────┘             │
│              ▼              ▼                     │
│     Self-Reflection  Sliding Window               │
│     多模型路由                                     │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│                6 个工具 🆕                          │
│  - multi_platform_comparison                      │
│  - query_single_platform                          │
│  - get_all_platform_products                      │
│  - search_product_by_image                        │
│  - semantic_product_search 🆕（向量+规则混合召回）  │
│  - search_product_knowledge 🆕（RAG 知识检索）     │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│          PlatformParallelAgent                    │
│  ThreadPoolExecutor (4 workers)                   │
│  京东 │ 淘宝 │ 拼多多 │ 苏宁                         │
└──────────────────────────────────────────────────┘
```

## 四种执行模式

| | ReAct | Plan-Execute | 语义推荐 🆕 | 引导式购物 🆕 |
|---|---|---|---|---|
| **场景** | 单商品比价 | 多商品对比、混合意图 | 场景/预算/处理器推荐 | 模糊需求、无明确型号 |
| **触发** | 默认兜底 | 多商品 / 对比词 | 场景词/预算词/处理器词 | "想买个手机""帮我挑" |
| **策略** | ReAct 循环 | Plan → Execute → Synthesize | ReAct + 向量召回 | ShoppingContext 状态机 |
| **特点** | 灵活 | 并行 + 依赖编排 | 语义相似度容错 | 槽位填充 + 主动引导 |

## 模块完成状态

| 模块 | 说明 | 状态 |
|------|------|:--:|
| M1: 行业配置框架 | Config Schema + 手机品类配置 + 注入通道 | ✅ |
| M2: 语义召回升级 | 向量召回 + 规则过滤混合检索，2048 维 embedding | ✅ |
| M3: RAG 知识库 | BM25 + 语义混合检索，手机领域知识增强 | ✅ |
| M4: 生成式推荐 | LLM 意图分解 + Rerank + 推荐解释（计划中） | 📋 |
| M5: 引导式购物 Agent | ShoppingContext 状态机 + 槽位填充 + 多轮购物 | ✅ |

## 功能特性

### 核心能力
- **ReAct 推理闭环**：Thought → Action → Observation → Final Answer
- **Plan-Execute 策略**：Phase 1 生成 JSON 计划 → Phase 2 每 Step 独立 mini-ReAct → Phase 3 综合回答
- **意图分类路由**：自动识别 4 种意图（推荐/查价/对比/购物），路由到最优执行模式
- **自反思纠错**：工具返回空结果时自动注入反思提示，引导重试或追问
- **多模型路由**：文本模型 DeepSeek V4 Flash，视觉模型豆包，Embedding 豆包
- **滑动窗口上下文**：保留最近 6 轮对话，理解"那小米14呢"等上下文指代

### 语义召回（M2）
- **向量+规则混合检索**：doubao-embedding-vision-251215（2048 维），语义相似度容错
- **商品 Embedding 预热**：启动时一次性计算并缓存，后续查询只计算 query embedding
- **功能开关**：`enable_vector_recall` 控制，关闭回退纯规则

### RAG 知识增强（M3）
- **BM25 + 语义混合检索**：alpha=0.7 语义为主，BM25 为辅，两路归一化融合
- **## 标题分块**：Markdown 文档按二级标题切分，携带 source/section 元数据
- **知识类型过滤**：chipset_compare / phone_review / spec_lookup / auto
- **真实场景规划**：文档中包含四层内容运营平台演进方案（摄入/加工/索引/监控）

### 引导式购物（M5）
- **ShoppingContext 状态机**：GREETING → SLOT_FILLING → SEARCHING → RECOMMENDING → FOLLOW_UP
- **槽位填充**：5 个槽位（场景/预算/品牌/处理器/屏幕），必填优先，最多追问 3 次
- **对比模式**：多款商品按维度（性能/拍照/续航/价格/屏幕）逐项对比

### IT3C 手机品类
- **17 个商品字段**：brand、processor、processor_brand、performance_tier、screen_size、battery、use_case_tags、description
- **处理器归一化**：骁龙→sd、天玑→mt、A 系列→apple、麒麟→kirin
- **场景标签**：gaming / photography / battery / business / student / budget / flagship

## 技术栈

- **LLM**：DeepSeek V4 Flash（文本）+ 火山引擎 ARK（视觉 + Embedding）
- **Embedding**：doubao-embedding-vision-251215（2048 维）
- **向量检索**：numpy 内存 + BM25 混合（mock 期）→ ChromaDB（生产期）
- **RAG**：自研 KnowledgeIndexer + KnowledgeRetriever + rank-bm25
- **框架**：Flask + SQLite
- **测试**：P0-P6 + IT3C + M1-M5 专项，150+ 测试用例

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 API Key
python app.py
```

### 环境变量

```bash
# DeepSeek（文本模型）
DEEPSEEK_API_KEY=your_key
DEEPSEEK_MODEL=deepseek-v4-flash

# 火山引擎 ARK（视觉 + Embedding）
ARK_API_KEY=your_key
ARK_VISION_MODEL=doubao-seed-2-0-pro-260215
ARK_EMBEDDING_MODEL=doubao-embedding-vision-251215
```

## 项目结构

```
price-agent/
  agent/
    react_engine.py        ← ReActAgent + ShoppingContext（M5）
    prompts.py             ← System prompt + 6 工具使用指南（M3）
  config/
    settings.py            ← 配置管理 + 多模型路由 + Embedding
    embedding.py           ← EmbeddingClient（doubao-embedding）
    industry_loader.py     ← 行业 Config 动态加载器（M1）
    industries/mobile.py   ← 手机品类配置（M1）
  tools/
    semantic_search_tool.py ← 语义推荐 + 向量召回（M2）
    rag_tool.py            ← RAG 知识检索工具（M3）
    knowledge_indexer.py   ← 知识索引 + BM25 混合检索（M3）
    multi_platform_tools.py ← 多平台比价工具
    image_search_tools.py  ← 图片搜索工具
    registry.py            ← 工具注册器
  platforms/
    parallel_agent.py      ← 并行查询 + Embedding 预热（M2）
    platform_database.py   ← 平台数据库（17 字段 Schema）
  knowledge/mobile/        ← 手机领域知识库（M3）
    processors/            ← 芯片对比文档
    reviews/               ← 机型评测文档
  tests/                   ← 评估框架（P0-P6 + IT3C）
  test_m1_config.py        ← M1 配置测试
  test_m2_recall.py        ← M2 召回测试
  test_m3_rag.py           ← M3 RAG 测试
  test_m5_shopping.py      ← M5 购物测试
  docs/modules/            ← 模块详细设计文档
```

## 文档

- [总规划](docs/下一代电商语义召回与Agent推荐-规划文档.md)
- [M0: 基础设施评估](docs/modules/00-基础设施评估.md)
- [M1: 行业配置框架](docs/modules/01-行业配置框架.md)
- [M2: 语义召回升级](docs/modules/02-语义召回升级.md)
- [M3: RAG 知识库](docs/modules/03-RAG知识库.md)
- [M4: 生成式推荐](docs/modules/04-生成式推荐.md)
- [M5: 引导式购物 Agent](docs/modules/05-引导式购物Agent.md)
