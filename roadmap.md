# Price Agent — 能力现状与发展路线

> 本文档基于项目当前代码库的实际实现，梳理已有能力、架构特点、以及在哪些方向存在可扩展空间。

---

## 一、项目定位

Price Agent 是一个**智能商品比价助手**，核心链路为：

```
用户输入（文字/图片） → LLM 意图识别 → 多平台并行搜索 → Agent 推理整合 → 生成回答
```

面向 IT3C 数字产品（手机、平板、耳机等），覆盖京东、淘宝、拼多多、苏宁四个电商平台。

---

## 二、当前已具备的核心能力

### 2.1 Agent 推理引擎

**入口路由**：`agent/react_engine.py` → `ReActAgent`

| 模式 | 触发条件 | 能力说明 |
|------|---------|---------|
| **ReAct 模式** | 单商品查价、推荐型查询 | 标准 Think → Act → Observe 循环，LLM 自主选择工具和 Skill |
| **Plan-Execute 模式** | 多商品对比、复杂分析 | LLM 生成多步执行计划（含步骤间依赖关系）→ 无依赖步骤并行执行 → 有依赖步骤串行执行 → Step 级 mini-ReAct 自反思纠错 → Phase 3 综合分析 |
| **Shopping 模式** | 无明确型号的购物咨询 | M5 槽位填充状态机，逐步引导用户明确需求 → 推荐候选 → 对比决策 |

**关键设计点**：

- **Skills 按需加载**：5 个 SKILL.md 技能模块，SkillLoader 解析 YAML frontmatter + markdown，LLM 通过 `load_skill` 元工具自主选择加载，用户支持 `/skill-name` 显式调用，加载后内容跨轮次持久化
- **多模型路由**：三个阶段的 LLM 调用使用不同模型（`model_plan` / `model_react` / `model_synthesize`），支持独立配置
- **自反思纠错**：工具调用结果为空或异常时，Step 级 mini-ReAct 循环（最多 2 轮反思），LLM 自主决定：换参数重试 / 换工具 / 放弃
- **$step{N} 引用语法**：Plan 中的步骤可引用前面步骤的结果，实现跨步骤数据共享
- **滑动窗口历史**：同会话内保留最近 6 轮 / 6000 字符的对话历史，用于理解指代

### 2.2 Skills 系统

**Skill 定义与加载**：`agent/skills/` 目录 — 5 个 SKILL.md 文件（YAML frontmatter + markdown body）

| Skill | 文件 | 描述 |
|------|------|------|
| `price_comparison` | [price_comparison.md](file:///Users/wenbowang/Documents/trae_projects/price-agent/agent/skills/price_comparison.md) | 跨平台比价：4 个 few-shot 示例，覆盖简单比价/指定平台/空结果/歧义 |
| `vision_search` | [vision_search.md](file:///Users/wenbowang/Documents/trae_projects/price-agent/agent/skills/vision_search.md) | 图片识别搜同款：VLM 识别 → 多平台比价流程指南 |
| `semantic_recommend` | [semantic_recommend.md](file:///Users/wenbowang/Documents/trae_projects/price-agent/agent/skills/semantic_recommend.md) | 场景推荐：3 个 few-shot 示例，覆盖场景/预算/处理器筛选 |
| `rag_knowledge` | [rag_knowledge.md](file:///Users/wenbowang/Documents/trae_projects/price-agent/agent/skills/rag_knowledge.md) | RAG 知识检索：评测/芯片对比/知识增强策略 |
| `shopping_guide` | [shopping_guide.md](file:///Users/wenbowang/Documents/trae_projects/price-agent/agent/skills/shopping_guide.md) | 引导式购物：槽位填充 → 推荐 → 比价 → 对比流程 |

**核心机制**：

- **SkillLoader**：[loader.py](file:///Users/wenbowang/Documents/trae_projects/price-agent/agent/skills/loader.py) — 扫描 `agent/skills/*.md`，解析 YAML frontmatter，生成 253 chars 紧凑 Catalog 注入 system prompt
- **load_skill 元工具**：注册为 OpenAI function tool，LLM 自主决定何时加载哪个 Skill，引擎拦截处理后注入 system 消息，加载后内容跨 ReAct 轮次持久化
- **用户显式调用**：支持 `/price_comparison` 等 Skill 前缀直接加载
- **预加载优化**：`_detect_intent()` 意图分类后自动预加载对应 Skill，避免常用场景多一轮 LLM 调用
- **Token 节省**：单场景 prompt 从 5,825 chars → 1,181-1,500 chars（节省 74-80%）
- **零代码扩展**：新增 Skill 只需添加一个 .md 文件，无需修改任何 Python 代码

### 2.3 工具系统

**工具注册与发现**：`tools/registry.py` — 基于 `@register_tool` 装饰器的声明式工具注册

| 工具 | 文件 | 功能 |
|------|------|------|
| `multi_platform_price_comparison` | [multi_platform_tools.py](file:///Users/wenbowang/Documents/trae_projects/price-agent/tools/multi_platform_tools.py) | 四平台并行比价，LLM 属性解析（自动提取颜色/内存/处理器/品牌）、多维匹配 |
| `search_product_by_image` | [image_search_tools.py](file:///Users/wenbowang/Documents/trae_projects/price-agent/tools/image_search_tools.py) | 图片搜同款：VLM 视觉模型识别商品 → 提取属性 → 多平台文本搜索比价 |
| `semantic_product_search` | [semantic_search_tool.py](file:///Users/wenbowang/Documents/trae_projects/price-agent/tools/semantic_search_tool.py) | 语义推荐：场景标签/预算/品牌/处理器多条件过滤 + Embedding 向量召回 + 规则过滤混合检索 + 性价比评分排序 |
| `search_product_knowledge` | [rag_tool.py](file:///Users/wenbowang/Documents/trae_projects/price-agent/tools/rag_tool.py) | RAG 知识检索：Knowledge Markdown 分块 + BM25 文本检索 + 语义向量检索混合，支持芯片对比/机型评测/参数规格三类知识 |
| `get_all_platform_products` | [multi_platform_tools.py](file:///Users/wenbowang/Documents/trae_projects/price-agent/tools/multi_platform_tools.py) | 全平台全量商品查询，去重后聚合展示 |

### 2.3 多模态能力

| 能力 | 实现 | 技术栈 |
|------|------|--------|
| **图片上传** | 前端 FileReader / 拖拽 / Ctrl+V 粘贴，后端 `api/upload-image` 接收 base64 或 multipart | Flask + File I/O |
| **图片识别** | VLM（豆包视觉模型）从图片中提取商品结构化属性：product_name / color / brand / category / confidence | 火山引擎 ARK Vision API |
| **图片搜索同款** | VLM 识别 → 属性提取 → 多平台并行文本搜索 → 比价结果输出 | 端到端工具调用链 |

限制：仅支持静态图片，不支持视频输入；识别目标限定为商品，不做通用画面理解。

### 2.4 多平台查询架构

**文件**：`platforms/` 目录

- **PlatformDatabase**：[platform_database.py](file:///Users/wenbowang/Documents/trae_projects/price-agent/platforms/platform_database.py) — 每个平台独立的 SQLite 数据库，17 字段 IT3C Schema（含品牌、处理器、场景标签等扩展属性）
- **PlatformParallelAgent**：[parallel_agent.py](file:///Users/wenbowang/Documents/trae_projects/price-agent/platforms/parallel_agent.py) — ThreadPoolExecutor 并行查询四个平台，线程锁保证连接安全
- **属性匹配引擎**：颜色别名映射 / 内存别名映射 / 处理器品牌别名映射 / 处理器型号关键词 → 多维评分排序（名称匹配度 × 颜色 × 内存 × 处理器 × 场景标签 × 价格）

### 2.5 推理可视化

**文件**：`agent/trace.py` + `static/js/app.js`

- **结构化 Trace 事件系统**：替代传统 print() 日志，每个推理步骤产生 Typed Event（intent / mode_select / plan_generated / step_start / step_end / react_round / tool_call / tool_result / reflection / synthesize_start / synthesize_end …）
- **SSE 实时流式**：后台线程运行 Agent → 通过 queue.Queue 实时推送 TraceEvent → 前端 SSE 消费并渲染
- **前端时间线**：[app.js](file:///Users/wenbowang/Documents/trae_projects/price-agent/static/js/app.js) 中的 `mapEventToNode()` + `renderTimeline()` 将事件渲染为可展开/折叠的垂直时间线面板

### 2.6 前端交互

| 功能 | 状态 |
|------|:--:|
| 会话管理（新建/切换/删除/搜索） | ✅ |
| 对话历史持久化（SQLite） | ✅ |
| Markdown 渲染（含价格高亮、平台标签） | ✅ |
| 图片上传 / 粘贴 / 拖拽 | ✅ |
| 图片预览 / 放大 | ✅ |
| 多标签页（商品管理 / 多平台比价 / 推理过程） | ✅ |
| 商品 CRUD（添加/编辑/删除，17字段表单） | ✅ |
| 平台切换（京东/淘宝/拼多多/苏宁标签页） | ✅ |
| 快捷提问 Chip | ✅ |
| Loading 动画 + 流式响应 | ✅ |
| 深色主题设计系统（CSS 变量 + Noto 字体 + 品牌色系） | ✅ |

### 2.7 知识库系统

**文件**：`tools/knowledge_indexer.py` + `knowledge/mobile/`

- **KnowledgeIndexer**：遍历 `knowledge/<industry>/` 下 .md 文件 → 按 `##` 标题分块（300-800 字符/块） → 批量 Embedding
- **KnowledgeRetriever**：BM25 + 语义向量混合检索
- **知识分类**：processors（芯片对比） / reviews（机型评测）
- **Embedding**：火山引擎 ARK 多模态 Embedding API → 2048 维向量 → 内存缓存

---

## 三、架构总览

```
┌────────────────────────────────────────────────────┐
│                    Frontend                        │
│  index.html + app.js + style.css                   │
│  (Bootstrap5 + marked.js)                          │
└─────────────┬──────────────────────────────────────┘
              │ SSE / REST
┌─────────────▼──────────────────────────────────────┐
│                  Flask App (app.py)                │
│  /api/chat/stream  /api/upload-image  ...          │
└─────────────┬──────────────────────────────────────┘
              │
┌─────────────▼──────────────────────────────────────┐
│               ReActAgent                           │
│  意图分类 → Skill 加载 → 模式路由 → 执行 → 综合回答    │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │  ReAct   │ │ Plan-Execute │ │  Shopping    │    │
│  │  (LLM)   │ │  (Planner)   │ │  (SlotFill)  │    │
│  └──────────┘ └──────────────┘ └──────────────┘    │
│  ┌──────────────────────────────────────────────┐   │
│  │  SkillLoader: SKILL.md × 5 + load_skill 元工具│   │
│  └──────────────────────────────────────────────┘   │
└─────────────┬──────────────────────────────────────┘
              │
┌─────────────▼──────────────────────────────────────┐
│                  Tool Registry                     │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────┐   │
│  │  比价     │ │  图搜    │ │ 语义推荐          │     │
│  │ (Multi)  │ │ (Image)  │ │ (Semantic+RAG)    │   │
│  └──────────┘ └──────────┘ └───────────────────┘   │
└─────────────┬──────────────────────────────────────┘
              │
┌─────────────▼──────────────────────────────────────┐
│         Platform Parallel Agent                    │
│  ┌────┐ ┌─────┐ ┌────┐ ┌──────┐                    │
│  │ JD │ │ TB  │ │PDD │ │SNG   │  ThreadPool        │
│  └────┘ └─────┘ └────┘ └──────┘                    │
│  SQLite × 4  (17-field IT3C Schema)                │
└────────────────────────────────────────────────────┘
              │
┌─────────────▼──────────────────────────────────────┐
│              External Services                     │
│  DeepSeek API (Text LLM)  │  ARK API (Vision+Emb)  │
└────────────────────────────────────────────────────┘
```

---

## 四、数据存储

| 存储 | 位置 | 内容 |
|------|------|------|
| 主 SQLite | `price_agent.db` | 会话历史（sessions + messages 表） |
| 平台 SQLite × 4 | `data/jd.db / taobao.db / pdd.db / suning.db` | 商品数据（17 字段），含硬编码 Mock 数据 |
| 图片上传 | `static/uploads/` | 用户上传的商品图片 |
| Embedding 缓存 | 内存 `_product_embedding_cache` | 商品文本向量预热缓存 |

---

## 五、已有能力 vs 待建设方向

### 5.1 已具备的能力（已完成）

| 能力 | 成熟度 | 说明 |
|------|:-----:|------|
| 多轮对话 Agent | ⭐⭐⭐⭐⭐ | ReAct + Plan-Execute + Shopping 三种模式，自反思纠错，多模型路由 |
| 多平台并行比价 | ⭐⭐⭐⭐⭐ | 四平台 ThreadPool，属性匹配引擎，6维评分排序 |
| 图片搜同款 | ⭐⭐⭐⭐ | VLM 识别 → 属性提取 → 文本比价，端到端工具链 |
| 语义推荐 | ⭐⭐⭐⭐ | Embedding 向量召回 + 规则过滤混合，性价比评分 |
| RAG 知识检索 | ⭐⭐⭐ | Markdown 分块 + BM25 + 语义混合检索 |
| Skills 按需加载 | ⭐⭐⭐⭐⭐ | 5 个 SKILL.md 模块，LLM 自主选择，/skill-name 显式调用，token 节省 74-80% |
| 推理可视化 | ⭐⭐⭐⭐⭐ | 结构化 Trace + SSE 流式 + 时间线渲染 |
| 会话持久化 | ⭐⭐⭐⭐ | SQLite 存储，滑动窗口历史，会话搜索 |
| 前端交互 | ⭐⭐⭐⭐ | 完整 CRUD，图片上传/粘贴/拖拽，响应式布局 |

### 5.2 可扩展方向（ 短期可实现）

这些方向基于现有架构可直接扩展，改动成本可控：

| 方向 | 现状 | 建议路径 |
|------|------|---------|
| **商品数据量扩充** | 仅 10+ 条 Mock 数据 | 接入真实电商 API 或爬虫，替换 `_PLATFORM_MOCK_DATA` |
| **新增电商平台** | 四平台硬编码 | 新增 PlatformConfig + PlatformDatabase + 注册到 `get_platform_ids()` |
| **新增商品垂直领域** | 仅 IT3C | 扩展 `_PLATFORM_MOCK_DATA` 及 17 字段 schema 支持服装/美妆等品类；配置新的 `industry_config` |
| **图片搜索扩展** | 仅识别商品属性 | VLM prompt 可扩展为：识别风格/材质/适用场景/相似款推荐 |
| **Embedding 模型切换** | 硬编码豆包 2048 维 | 抽象 EmbeddingProvider 接口，提取 `settings.py` 配置项 |
| **知识库扩充** | 仅 2 个手机评测 + 2 个芯片对比 | 增加 `knowledge/<industry>/` 下的 .md 文件即可自动索引入库 |
| **前端体验优化** | 功能齐全但交互细节可打磨 | 流式打字机效果、搜索结果卡片化、价格趋势图、分享功能 |
| **部署容器化** | 无 Dockerfile | 添加 Dockerfile + docker-compose，gunicorn + gevent + nginx |
| **监控与日志** | 仅 print() | 接入标准 logging，添加接口耗时统计、工具调用成功率监控 |

### 5.3 中期演进方向

这些方向需要新增模块或较大重构：

| 方向 | 说明 | 涉及模块 |
|------|------|---------|
| **结构化 Memory** | 用户画像向量化、跨会话兴趣记忆、搜索偏好留存 | 新增 `memory/` 模块，参考 TraceCollector 的事件驱动设计 |
| **个性化推荐** | 基于用户历史搜索/购买行为的个性化排序 | `semantic_search_tool.py` 增加用户特征输入维度 |
| **多模态混合检索** | 支持图片+图片、图片+文字、视频帧+文字的混合 Query | `tools/` 新增 `multi_modal_search_tool.py` |
| **向量数据库** | 替代当前内存 Embedding 缓存，支持大规模商品库 | 引入 Chroma / Milvus / Qdrant，替换 `_product_embedding_cache` |
| **视频帧理解** | VLM 对视频关键帧做商品识别，支持短视频搜同款 | VLM API 增加视频帧采样 + 逐帧识别 + 结果聚合 |
| **通用视觉搜索** | 从"仅搜商品"扩展到"万物可搜"（风景/建筑/动植物等） | VLM prompt 重构 + 通用视觉知识库 |
| **本地生活服务** | 新增本地生活品类（餐饮、门店、团购），增加地理位置维度 | 新增 industry config + schema 升级 + 门店坐标存储与距离计算 |

### 5.4 长期愿景方向

这些方向涉及基础设施或算法研发层面的升级：

| 方向 | 说明 |
|------|------|
| **在线策略学习** | 引入用户反馈信号（点击/购买/满意度），在线 RL 训练优化 Agent 的搜索策略和回答质量 |
| **图搜 Embedding 模型** | 训练独立的商品图像 Embedding 模型，替代"VLM→属性→文本匹配"链路，实现真正的视觉特征同款召回 |
| **Agentic Planner 编排引擎** | 将 Plan-Execute 升级为通用任务编排框架，支持自定义任务模板、超时重试策略、结果缓存 |
| **VLM 相关性判别** | 训练或使用 VLM 对搜索结果做画面内容相关性判断，替代纯文本匹配 |
| **多 Agent 协作** | 多个专业 Agent 协同（查价 Agent + 推荐 Agent + 问答 Agent + 售后 Agent） |
| **实时价格监控** | 定时轮询商品价格变化 → 价格走势图 → 降价提醒/推送 |

### 5.5 Skills 架构（✅ 已完成 — 2026-05-26）

#### 实现方案

将巨型单体 `SYSTEM_PROMPT`（5,825 chars）拆分为 5 个独立 `SKILL.md` 技能模块（YAML frontmatter + markdown），采用 Claude Code 风格的 Skills 设计：

- **SkillLoader**：扫描 `agent/skills/*.md`，解析 frontmatter 元数据，生成 253 chars 紧凑 Catalog
- **load_skill 元工具**：注册为 OpenAI function tool，LLM 根据用户意图自主决定加载哪个 Skill，引擎拦截后注入 system 消息并跨轮次持久化
- **用户显式调用**：支持 `/price_comparison` 等前缀直接加载 Skill
- **预加载优化**：`_detect_intent()` 意图分类后自动预加载对应 Skill（避免常用场景多一轮 LLM 调用）
- **Catalog 始终可见**：每个 Skill 一行描述（~250 chars），LLM 始终知道有哪些可用 Skill

#### 实际效果

| 场景 | 激活 Skills | 原 prompt | Skills 后 | 节省 |
|------|-------------|:---:|:---:|:---:|
| 简单比价 | price_comparison | 5,825 chars | 1,181 chars | **80%** |
| 图片搜同款 | vision_search + price_comparison | 5,825 chars | 1,329 chars | **77%** |
| 推荐 + 比价 | semantic_recommend + price_comparison | 5,825 chars | ~1,500 chars | **74%** |
| 对比 + 知识 | price_comparison + rag_knowledge | 5,825 chars | ~1,400 chars | **76%** |

**向后兼容**：Skill 加载失败或未命中时回退完整 `SYSTEM_PROMPT`。116 测试全部通过，eval 综合通过率 95.9% 零回归。

**零代码扩展**：新增 Skill 只需添加一个 .md 文件到 `agent/skills/`，无需修改任何 Python 代码。

> 原始设计文档：[docs/skills-architecture-plan.md](file:///Users/wenbowang/Documents/trae_projects/price-agent/docs/skills-architecture-plan.md)

---

## 六、技术栈清单

| 层级 | 技术 | 用途 |
|------|------|------|
| **前端** | Bootstrap 5 + vanilla JS + marked.js | 页面布局、交互、Markdown 渲染 |
| **后端框架** | Flask + Flask-CORS | Web 服务、API 路由 |
| **AI Agent** | 自建 ReActAgent | Agent 推理引擎（三种模式） |
| **LLM 文本** | DeepSeek API（OpenAI 兼容） | ReAct 推理、Plan 生成、Phase 3 综合分析 |
| **LLM 视觉** | 火山引擎 ARK Vision（豆包） | 图片识别、商品属性提取 |
| **Embedding** | 火山引擎 ARK Embedding（2048维） | 向量召回、语义搜索 |
| **检索** | rank-bm25 + numpy cosine | BM25 + 语义向量混合检索 |
| **数据库** | SQLite × 5 | 会话历史 + 四平台商品库 |
| **并发** | concurrent.futures.ThreadPoolExecutor | 多平台并行查询 |
| **流式** | Flask SSE + threading + queue.Queue | Agent 推理过程实时推送 |
| **部署** | Flask 开发服务器（待生产化） | 建议: gunicorn + gevent + nginx |

---

## 七、待办事项速览

### P0 — 阻塞性
- [ ] 生产环境部署方案（gunicorn + gevent + nginx，解决 SSE 长连接兼容性）
- [ ] Dockerfile + docker-compose 容器化

### P1 — 短期
- [ ] 商品数据从 Mock 替换为真实数据源
- [ ] 前端流式打字机效果（当前是整体返回后渲染）
- [ ] API 接口鉴权（当前 `/api/chat/stream` 无认证）

### P2 — 中期
- [x] **Skills 化改造**（✅ 已完成 — SKILL.md 驱动 + load_skill 元工具 + /skill-name 显式调用，token 节省 74-80%）
- [ ] 结构化 Memory 模块（向量化用户画像 + 跨会话兴趣留存）
- [ ] Embedding 向量数据库（替换内存缓存）
- [ ] 图搜 VLM prompt 优化（支持更多商品品类识别）

### P3 — 长期
- [ ] 用户反馈闭环（点击/满意度 → RL 训练）
- [ ] 独立商品图搜 Embedding 模型
- [ ] 实时价格监控 + 降价提醒
