# Price Agent — 智能识物比价 AI 助手

基于 **ReAct + Plan-Execute 混合策略**的 LLM Agent，支持文本查询和图片识物两种入口，在京东、淘宝、拼多多、苏宁 4 个电商平台并行比价，帮助消费者快速找到最具性价比的商品。

> 当前为 mock 数据验证版本。架构上预留了 DataSource 抽象层，验证通过后可替换为真实电商数据源。

## 核心架构

```
用户输入（文本 / 图片）
        │
        ▼
┌─────────────────────────────────┐
│        ReActAgent 引擎           │
│                                 │
│  _is_complex()  →  简单 / 复杂   │
│       │              │          │
│       ▼              ▼          │
│  _react_loop()  _plan_and_      │
│  (ReAct 模式)   execute()       │
│                 (Plan-Execute)  │
│       │         Phase 1: Plan   │
│       │         Phase 2: 每Step │
│       │         独立mini-ReAct  │
│       │         Phase 3: 综合   │
│       │              │          │
│       └──────┬───────┘          │
│              ▼                  │
│     Self-Reflection 纠错        │
│     Sliding Window 上下文       │
│     多模型路由 (5 模型)          │
└──────────────┬──────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│          4 个工具                 │
│  - multi_platform_comparison     │
│  - query_single_platform         │
│  - get_all_platform_products     │
│  - search_product_by_image       │
└──────────────┬──────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│     PlatformParallelAgent        │
│  ThreadPoolExecutor (4 workers)  │
│  京东 │ 淘宝 │ 拼多多 │ 苏宁        │
└──────────────────────────────────┘
```

### 两种推理模式

| | ReAct 模式 | Plan-Execute 模式 |
|---|---|---|
| **适用场景** | 单商品比价、简单查询 | 多商品对比、复杂分析 |
| **流程** | Thought → Action → Observation → Final Answer 循环 | Phase 1 Plan → Phase 2 每 Step 独立 mini-ReAct 循环 → Phase 3 Synthesize |
| **Step 验证** | LLM 每轮自主判断 | 每 Step 内部：执行→观察→空则反思重试/换工具→完成 |
| **LLM 调用次数** | 1-3 次 | 2 + N×(0~2) 次（N=Step 数，有数据时 Round 1 直接返回无额外调用） |
| **工具并行** | 单工具 | 独立 Step ThreadPoolExecutor 并行（各 Step 内部 mini-ReAct 互不干扰） |
| **模型** | `ARK_MODEL`（默认） | Plan 用 `ARK_MODEL_PLAN`，Synthesize 用 `ARK_MODEL_SYNTHESIZE`，Step ReAct 用 `ARK_MODEL` |

## 功能特性

### 核心能力
- **ReAct 推理闭环**：Thought → Action → Observation → Final Answer，思考先行 + 工具调用 + 结果观察 + 最终回答
- **Plan-Execute 策略**：Phase 1 LLM 生成 JSON 执行计划 → Phase 2 每 Step 独立 mini-ReAct（执行→观察→空则反思重试/换工具/放弃）→ Phase 3 综合回答，`$step{N}` 引用语法实现步骤间数据传递
- **自反思纠错**：工具返回空结果时，ReAct 模式注入反思提示引导 LLM 重试或追问，Plan-Execute 模式自动放宽属性筛选后重试
- **多模型路由**：5 个阶段可独立配置模型（默认/Plan/Synthesize/Parse/Vision），平衡质量与成本
- **滑动窗口上下文**：保留最近 6 轮对话，过滤 ReAct 中间产物，支持"那小米14呢"、"这两个哪个更值得买"等上下文指代

### 搜索入口
- **文本搜索**：自然语言输入商品名 + 颜色/内存属性，支持品牌别名（"水果手机" → "iPhone"、"米14" → "小米14"）
- **图片识物**：多模态 LLM 识别商品属性（品牌、型号、颜色），自动转入文本搜索链路比价
- **前端上传**：📷 按钮上传 / Ctrl+V 粘贴 / 拖拽上传，缩略图预览 + 点击放大 + 一键删除，每次限一张

### 数据与存储
- **4 平台独立数据库**：`platform_{jd/taobao/pdd/suning}.db`，每个平台的商品有独立定价
- **属性匹配打分**：color +1、memory +1，同分时按价格升序打破平局，支持模糊匹配兜底
- **会话持久化**：`price_agent.db` 存储所有历史会话和消息

### 前端交互
- **三栏布局**：左侧会话历史（折叠/展开）、中间聊天区、右侧面板（商品管理 / 比价 / 推理过程）
- **商品管理**：4 平台切换、模糊搜索、模态框全字段编辑、折叠式添加表单
- **推理过程**：自动切换到推理 Tab，实时展示 Agent 的 Thought / Action / Observation

## 项目结构

```
price-agent/
├── app.py                              # Flask Web 应用（后端入口，5001 端口）
├── main.py                             # 命令行 REPL 版本
├── config/
│   └── settings.py                     # 配置中心（5 模型路由 + Agent 参数 + 复杂度/反思配置）
├── agent/
│   ├── react_engine.py                 # ReActAgent 核心引擎（混合策略 + 自反思 + 多模型 + 滑动窗口）
│   └── prompts.py                      # SYSTEM_PROMPT（~140 行）+ PLAN_PROMPT_TEMPLATE
├── tools/
│   ├── registry.py                     # 工具注册器（@register_tool 装饰器 + 单例 registry）
│   ├── multi_platform_tools.py         # 3 个文本搜索工具 + LLM 属性解析
│   ├── image_search_tools.py           # 图片搜索工具（base64 预处理 + 多模态识别 → 比价）
│   └── __init__.py
├── platforms/
│   ├── platform_config.py              # 4 平台静态配置（名称、图标、颜色、DB 路径）
│   ├── platform_database.py            # 单平台数据库（CRUD + 属性打分匹配 + 颜色/内存别名扩展）
│   ├── parallel_agent.py               # 多平台并行查询（ThreadPoolExecutor + 线程锁 + 比价汇总）
│   └── __init__.py
├── database/
│   ├── connection.py                   # 线程安全 SQLite 连接（threading.local）
│   └── models.py                       # 会话/消息数据模型
├── templates/
│   └── index.html                      # SPA 前端（Bootstrap 5 三栏布局 + 模态框）
├── static/
│   ├── css/style.css                   # 自定义样式（布局 + 图片预览 + 拖拽 + 滚动条）
│   ├── js/app.js                       # SPA 控制器（会话/商品/比价/图片上传 ~800 行）
│   └── uploads/                        # 用户上传图片（gitignored）
├── tests/
│   ├── eval_helpers.py                 # 评估基础设施（ground truth 计算 + 幻觉得分 + 记录器）
│   ├── eval_p0_unit.py                 # P0 单元测试（无 LLM，43 case）
│   ├── eval_p1_parse.py                # P1 属性解析测试（17 case）
│   ├── eval_p2_e2e.py                  # P2 端到端测试（17 case）
│   ├── eval_p3_boundary.py             # P3 能力边界测试（15 case）
│   ├── eval_p5_optimization.py         # P5 优化验证（13 case）
│   ├── eval_p6_image.py                # P6 图片搜索测试（7 case）
│   ├── eval_p4_benchmark.py            # P4 回归基准汇总
│   └── eval_results/                   # 评估结果 JSON 输出
├── platform_jd.db                      # 京东平台数据库（10 个商品）
├── platform_taobao.db                  # 淘宝平台数据库（8 个商品）
├── platform_pdd.db                     # 拼多多平台数据库（7 个商品）
├── platform_suning.db                  # 苏宁平台数据库（7 个商品）
├── price_agent.db                      # 会话/消息数据库
├── requirements.txt
├── .env                                # API 密钥 + 模型配置
├── .env.example                        # 配置模板
├── .gitignore
├── README.md
├── 评估文档.md                          # 7 阶段评估方案与实测结果
├── 优化文档.md                          # 15 项已完成优化 + 4 个待探索方向
└── MULTI_PLATFORM_README.md            # 多平台比价详细文档
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API

```bash
cp .env.example .env
```

编辑 `.env`：

```
ARK_API_KEY=your_api_key_here

# 多模型路由（不设置则全部回退到 ARK_MODEL）
ARK_MODEL=your_default_model              # ReAct 循环
ARK_MODEL_PLAN=your_plan_model            # Phase 1 计划生成（推荐结构化输出能力强的模型）
ARK_MODEL_SYNTHESIZE=your_synthesize_model # Phase 3 综合分析（推荐推理能力强的模型）
ARK_MODEL_PARSE=your_parse_model          # 属性解析（简单任务，轻量模型即可）
ARK_VISION_MODEL=your_vision_model        # 图片识别（需多模态模型）
```

### 3. 启动

```bash
python3 app.py
```

访问 **http://127.0.0.1:5001**

## 工具说明

4 个工具均通过 `@register_tool` 装饰器注册到全局 `tool_registry` 单例，Agent 通过 OpenAI 兼容的 function calling 自动选择。

### 1. `multi_platform_price_comparison`
在京东、淘宝、拼多多、苏宁 4 个平台并行查询商品价格。如果 `product_name` 中包含颜色/内存关键词（如"黑色"、"256GB"），自动调用 LLM 解析属性。返回各平台价格对比、最低价、均价、价差。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `product_name` | string | 是 | 商品名称，可含颜色/内存 |
| `color` | string | 否 | 颜色筛选 |
| `memory` | string | 否 | 内存/容量筛选 |

### 2. `query_single_platform_product`
查询单个指定平台的商品信息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `platform_id` | string | 是 | 平台：jd / taobao / pdd / suning |
| `product_name` | string | 是 | 商品名称 |
| `color` | string | 否 | 颜色筛选 |
| `memory` | string | 否 | 内存/容量筛选 |

### 3. `get_all_platform_products`
并行获取 4 个平台的所有商品列表，无需参数。

### 4. `search_product_by_image`
接收商品图片 URL，多模态 LLM 提取商品属性（品牌、型号、颜色、品类、置信度），自动转入文本搜索链路比价。远程图片自动下载转 base64 以解决 API 服务器网络可达性问题。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image_url` | string | 是 | 图片 URL 或 data: URL |
| `color` | string | 否 | 追加颜色偏好 |
| `memory` | string | 否 | 追加容量偏好 |

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web 界面 |
| `/api/chat` | POST | 聊天接口，支持 `image_url` 可选参数 |
| `/api/image-search` | POST | 独立图片搜索接口 |
| `/api/upload-image` | POST | 图片上传（multipart 或 base64 JSON） |
| `/api/sessions` | GET/POST | 会话列表 / 创建 |
| `/api/sessions/<id>` | DELETE | 删除会话 |
| `/api/sessions/<id>/messages` | GET | 获取会话消息 |
| `/api/multi-platform/compare` | POST | 直接多平台比价 |
| `/api/multi-platform/products` | GET | 所有平台商品汇总 |
| `/api/platforms` | GET | 平台列表 |
| `/api/platforms/<pid>/products` | GET/POST | 平台商品列表 / 添加 |
| `/api/platforms/<pid>/products/<id>` | PUT/DELETE | 更新 / 删除商品 |

## 数据库设计

### 平台数据库（`platform_{jd/taobao/pdd/suning}.db`）

```sql
CREATE TABLE products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name    TEXT NOT NULL,       -- 商品名称
    price           REAL NOT NULL,       -- 参考价
    stock           INTEGER NOT NULL,    -- 库存
    category        TEXT NOT NULL,       -- 品类（手机/平板/耳机）
    platform_price  REAL,                -- 平台实际售价
    shipping_fee    REAL DEFAULT 0,      -- 运费
    is_in_stock     BOOLEAN DEFAULT 1,   -- 是否有货
    color           TEXT,                -- 颜色
    memory          TEXT                 -- 内存/容量
);
```

### 会话数据库（`price_agent.db`）

```sql
CREATE TABLE sessions (id, session_id, created_at);
CREATE TABLE messages (id, session_id, role, content, timestamp);
```

## 配置说明

所有配置项可通过 `.env` 或 `config/settings.py` 修改：

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|--------|------|
| API Key | `ARK_API_KEY` | - | 必填，火山引擎 Ark API 密钥 |
| 默认模型 | `ARK_MODEL` | pro | ReAct 循环使用 |
| Plan 模型 | `ARK_MODEL_PLAN` | code-preview | Phase 1 计划生成 |
| 综合模型 | `ARK_MODEL_SYNTHESIZE` | pro | Phase 3 综合分析 |
| 解析模型 | `ARK_MODEL_PARSE` | pro | 属性提取 |
| 视觉模型 | `ARK_VISION_MODEL` | pro | 图片识别 |
| 最大推理轮数 | - | 5 | ReAct 循环上限 |
| Plan 最大步数 | - | 8 | 执行计划步骤上限 |
| 历史窗口轮数 | - | 6 | 滑动窗口保留轮数 |
| 历史窗口字符 | - | 6000 | 滑动窗口字符上限 |
| 反思重试次数 | - | 2 | 空结果最大重试次数 |
| 复杂度关键词 | `COMPLEXITY_KEYWORDS` | 18 个 | 逗号分隔追加 |

## 评估体系

7 阶段评估，105+ 测试 case，自动化 ground truth 计算 + 幻觉检测 + 结果持久化。

```bash
python3 tests/eval_p0_unit.py            # P0 单元测试（无 LLM，43 case）
python3 tests/eval_p1_parse.py           # P1 属性解析（17 case）
python3 tests/eval_p2_e2e.py             # P2 端到端 ReAct + Plan-Execute（17 case）
python3 tests/eval_p3_boundary.py        # P3 能力边界（15 case）
python3 tests/eval_p5_optimization.py    # P5 优化验证（13 case）
python3 tests/eval_p6_image.py           # P6 图片搜索（7 case）
python3 tests/eval_p4_benchmark.py       # P4 汇总所有阶段
```

### 最新结果（2026-05-11）

| 阶段 | 通过率 | 说明 |
|------|:------:|------|
| P0 单元测试 | 100% (43/43) | CRUD、打分匹配、并行查询、回归、复杂度判断、依赖注入、空结果检测、反思消息 |
| P1 参数提取 | 100% (17/17) | 属性提取 + 品牌别名改写 |
| P2 端到端 | 100% (17/17) | ReAct + Plan-Execute 混合（per-step mini-ReAct） |
| P3 能力边界 | 100% (15/15) | 不存在商品、歧义、异常、矛盾需求、多轮对话 |
| P5 优化验证 | 100% (13/13) | 自反思纠错、System Prompt 质量、依赖注入、复杂度路由 |
| P6 图片搜索 | 100% (7/7) | 工具注册、属性解析、E2E 识别→比价 |
| **综合** | **100% (105/105)** | 全阶段通过 |

### 各维度指标

| 维度 | 得分 | 说明 |
|------|:----:|------|
| 基础功能正确率 | 100% | P0 全通过 |
| 参数提取准确率 | 100% | 属性+别名全正确 |
| 答案正确率 | 100% | 全部正确 |
| 幻觉率 | 0% | 无 |
| 优雅降级率 | 100% | 异常输入全部正确处理 |
| 自反思纠错 | 100% | 空结果自动重试或追问 |
| System Prompt 遵循 | 100% | 输出格式符合要求 |

## 技术栈

- **Python 3.10+**
- **OpenAI API（兼容）** — LLM 推理，支持 5 模型路由
- **Flask** — Web 框架
- **SQLite** — 数据存储（5 个 .db 文件）
- **ThreadPoolExecutor** — 多平台并行查询 + Plan-Execute 并行步骤
- **Bootstrap 5** — 前端 UI

## 许可证

MIT License
