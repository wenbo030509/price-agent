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
│                                                  │
│  _detect_intent() → 意图分类                       │
│       │              │              │             │
│       ▼              ▼              ▼             │
│  recommendation  comparison    shopping           │
│  (语义推荐)     (Plan-Execute) (引导式购物)          │
│       │              │              │             │
│       ▼              ▼              ▼             │
│  _react_loop   _plan_and_     _guided_shopping    │
│  +intent_hint  execute()      + ShoppingContext   │
│       │         Phase 1: Plan       │             │
│       │         Phase 2: mini-ReAct │             │
│       │         Phase 3: Synthesize │             │
│       │              │              │             │
│       └──────┬───────┴──────┬───────┘             │
│              ▼              ▼                     │
│     Self-Reflection  Sliding Window               │
│     多模型路由                                      │
└──────────────┬───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│                6 个工具                           │
│  - multi_platform_comparison                      │
│  - query_single_platform                          │
│  - get_all_platform_products                      │
│  - search_product_by_image                        │
│  - semantic_product_search  （向量+规则混合召回）    │
│  - search_product_knowledge  （RAG 知识检索）      │
└──────────────┬───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│          PlatformParallelAgent                   │
│  ThreadPoolExecutor (4 workers)                  │
│  京东 │ 淘宝 │ 拼多多 │ 苏宁                        │
└──────────────────────────────────────────────────┘
```

## 四种执行模式

| | ReAct | Plan-Execute | 语义推荐  | 引导式购物 |
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
| M6: Trace 数据处理工坊 | trace → SFT 训练数据集构建 + 质量评分 + LLM-Judge + 人工审核 | ✅ |
| **推理可视化** | TraceEvent 结构化事件 + SSE 流式 + 模式可视化 + 调试仪表盘 | ✅ |

## 功能特性

### 核心能力
- **ReAct 推理闭环**：Thought → Action → Observation → Final Answer
- **Plan-Execute 策略**：Phase 1 生成 JSON 计划 → Phase 2 每 Step 独立 mini-ReAct → Phase 3 综合回答
- **意图分类路由**：自动识别 4 种意图（推荐/查价/对比/购物），路由到最优执行模式
- **Skills 按需加载**：5 个 SKILL.md 技能模块，LLM 通过 `load_skill` 元工具自主选择，用户 `/skill-name` 显式调用
- **自反思纠错**：工具返回空结果时自动注入反思提示，引导重试或追问
- **多模型路由**：文本模型 DeepSeek V4 Flash，视觉模型豆包，Embedding 豆包
- **滑动窗口上下文**：保留最近 6 轮对话，理解"那小米14呢"等上下文指代

### 语义召回（M2）
- **向量+规则混合检索**：doubao-embedding-vision-251215（2048 维），语义相似度容错
- **商品 Embedding 预热**：启动时计算并持久化到 `embeddings_cache.pkl`，后续启动仅增量更新新增/变更商品（↓74% API 调用）
- **MD5 指纹检测**：按 `build_product_text` 输出计算指纹，自动识别商品内容变更
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

### 推理可视化（L1-L4）
- **结构化 Trace 事件**：13 种事件类型（intent/mode/plan/step/tool/reflection/shopping/skill_load），替代 print() 驱动
- **SSE 实时流式传输**：`/api/chat/stream` 端点，前端 ReadableStream 消费，推理步骤逐个实时出现
- **模式特定可视化**：
  - M5 购物状态机：6 阶段横向进度条 + 槽位填充 chip
  - Plan-Execute DAG：并行/串行分组 + 步骤状态 pending→running→done/error（pulse 动画）
  - 时间瀑布：步骤耗时水平条形图
  - 模型路由徽章：节点标题行内显示模型名称
- **调试仪表盘**：Trace 自动保存 → 列表（按会话过滤）→ 逐步骤回放（速度 0.5x-5x）→ 性能摘要

### Trace 数据处理工坊（M6）
- **独立页面**：`/training-data`，4 步向导式处理链路
- **Trace 列表**：分页表格（50条/页）+ 按意图/模式/工具数筛选 + 点击展开详情
- **格式提取**：Trace → OpenAI SFT fine-tuning JSONL，左右对比视图 + 在线编辑
- **质量评分**：从业务视角评估（Agent 能力展现/执行质量/回答可信度/数据完整度）
- **LLM-as-Judge**：调用 DeepSeek 从 5 个维度（工具选择/参数提取/数据引用/回答质量/训练价值）评估样本质量
- **人工审核**：卡片式审核列表 + ✓通过/✗拒绝 + 按状态筛选 + 批量操作
- **JSONL 导出**：符合 OpenAI Chat Completions fine-tuning 格式，可对接 HuggingFace TRL / Unsloth
- **处理规模**：188 条 Trace → ~52 条高价值训练样本（≥70分）

### Skills 架构（Prompt 按需组合）
- **SKILL.md 驱动**：5 个技能模块（比价/图片搜索/语义推荐/RAG 知识/购物引导），YAML frontmatter + markdown 定义
- **LLM 自主选择**：`load_skill` 元工具让 LLM 根据用户意图自行决定加载哪个技能
- **用户显式调用**：支持 `/price_comparison` 等 Skill 前缀直接调用
- **上下文持久化**：加载后的 Skill 内容跨 ReAct 轮次持久保留
- **Token 优化**：Catalog 仅 253 chars（vs 原 5,825 chars SYSTEM_PROMPT），单场景节省 74-80%
- **零代码扩展**：新增 Skill 只需添加一个 .md 文件

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
    react_engine.py        ← ReActAgent + ShoppingContext（M5）+ Skills 架构
    trace.py               ← TraceEvent 结构化事件系统（L1-L2）
    prompts.py             ← 公共 Prompt 片段（COMMON_RULES/FORMAT/ERROR）
    skills/
      loader.py            ← SkillLoader：SKILL.md 解析 + Catalog 生成
      price_comparison.md  ← 比价 Skill（4 个 few-shot）
      vision_search.md     ← 图片搜索 Skill
      semantic_recommend.md ← 语义推荐 Skill（3 个 few-shot）
      rag_knowledge.md     ← RAG 知识检索 Skill
      shopping_guide.md    ← 购物引导 Skill
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
  scripts/
    training_data.py       ← M6 Trace 数据处理 + 质量评分 + LLM-Judge（~680行）
  tests/
    test_trace.py          ← L1/L2 结构化事件 + SSE 流式测试（72 用例）
    conftest.py            ← pytest fixtures（client/indexer/retriever/agent）
    test_m1_config.py      ← M1 配置测试
    test_m2_recall.py      ← M2 召回测试
    test_m3_rag.py         ← M3 RAG 测试
    test_m5_shopping.py    ← M5 购物测试
    test_react_engine.py   ← ReActEngine 核心测试
  eval/                    ← 评估框架（P0-P6 + IT3C 回归套件）
    results/traces/        ← L4 自动保存的 trace 文件（~188条）
  templates/
    training.html          ← M6 Trace 数据处理工坊页面
  static/js/
    training.js            ← M6 工坊前端交互逻辑（~630行）
  docs/modules/            ← 模块详细设计文档
  docs/trace-data-processing-plan.md  ← M6 完整方案文档
```

## 文档

- [总规划](roadmap.md)

