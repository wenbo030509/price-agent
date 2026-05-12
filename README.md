# Price Agent — 智能识物比价 AI 助手

基于 **ReAct + Plan-Execute 混合策略**的 LLM Agent，支持文本查询和图片识物两种入口，在京东、淘宝、拼多多、苏宁 4 个电商平台并行比价，并具备**语义推荐**能力（按使用场景/预算/处理器筛选推荐商品）。

> 当前为 mock 数据验证版本。架构上预留了 DataSource 抽象层，验证通过后可替换为真实电商数据源。

## 核心架构

```
用户输入（文本 / 图片）
        │
        ▼
┌─────────────────────────────────┐
│        ReActAgent 引擎           │
│                                 │
│  _detect_intent()  →  意图分类   │
│       │              │          │
│       ▼              ▼          │
│  recommendation    comparison   │
│  (语义推荐模式)   (Plan-Execute) │
│       │              │          │
│       ▼              ▼          │
│  _react_loop()  _plan_and_      │
│  + intent_hint  execute()       │
│       │         Phase 1: Plan   │
│       │         Phase 2: 每Step │
│       │         独立mini-ReAct  │
│       │         Phase 3: 综合   │
│       │              │          │
│       └──────┬───────┘          │
│              ▼                  │
│     Self-Reflection 纠错        │
│     Sliding Window 上下文       │
│     多模型路由                   │
└──────────────┬──────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│          5 个工具                 │
│  - multi_platform_comparison     │
│  - query_single_platform         │
│  - get_all_platform_products     │
│  - search_product_by_image       │
│  - semantic_product_search 🆕    │
└──────────────┬──────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│     PlatformParallelAgent        │
│  ThreadPoolExecutor (4 workers)  │
│  京东 │ 淘宝 │ 拼多多 │ 苏宁        │
└──────────────────────────────────┘
```

### 三种执行模式

| | ReAct 模式 | Plan-Execute 模式 | 语义推荐模式 🆕 |
|---|---|---|---|
| **适用场景** | 单商品比价、简单查询 | 多商品对比、复杂分析 | "推荐游戏手机"、"5000以内性价比手机"、"骁龙处理器手机有哪些" |
| **触发条件** | 默认兜底 | 多商品 + 对比词 | 场景词/预算词/处理器词 + 无明确型号 |
| **首选工具** | 任意 | 按 Plan 执行 | `semantic_product_search` |
| **LLM 调用** | 1-3 次 | 2 + N×(0~2) 次 | 1-3 次 |

## 功能特性

### 核心能力
- **ReAct 推理闭环**：Thought → Action → Observation → Final Answer
- **Plan-Execute 策略**：Phase 1 生成 JSON 计划 → Phase 2 每 Step 独立 mini-ReAct → Phase 3 综合回答，`$step{N}` 引用语法含 `[N]` 列表索引支持
- **语义推荐 🆕**：意图分类自动识别推荐型查询 → 调用 `semantic_product_search` 按场景/预算/处理器/性能层级筛选推荐
- **自反思纠错**：工具返回空结果时自动注入反思提示，引导重试或追问
- **多模型路由**：文本模型统一 DeepSeek V4 Flash，视觉模型豆包
- **滑动窗口上下文**：保留最近 6 轮对话，理解"那小米14呢"等上下文指代

### 搜索入口
- **文本搜索**：自然语言输入，支持颜色/内存/处理器/预算多维度属性提取
- **图片识物**：多模态 LLM 识别商品属性，自动转入文本搜索链路比价
- **品牌别名**："水果手机"→"iPhone"、"米14"→"小米14"、"ip15"→"iPhone 15"

### IT3C 手机品类增强 🆕
- **17 个商品字段**：新增 brand、processor、processor_brand、performance_tier、screen_size、battery、use_case_tags、description
- **8 维度属性匹配评分**：颜色 + 内存 + 处理器品牌 + 处理器型号 + 使用场景 + 性能层级（max=6）
- **处理器归一化**：骁龙→sd、天玑→mt、A 系列/M 系列→apple、麒麟→kirin、猎户座→exynos
- **使用场景标签**：gaming / photography / battery / business / student / budget / flagship
- **预算硬过滤**：SQL 级别过滤 + 性价比评分排序

### 数据与存储
- **4 平台独立数据库**：每个平台 10-12 个商品，覆盖手机/平板/耳机
- **主 DB 纯会话管理**：商品数据统一走 `platforms.PlatformDatabase`
- **会话持久化**：`price_agent.db` 存储历史会话和消息

## 项目结构

```
price-agent/
├── app.py                              # Flask Web 应用（5001 端口）
├── config/
│   └── settings.py                     # DeepSeek API 配置 + 多模型路由
├── agent/
│   ├── react_engine.py                 # ReActAgent 核心引擎（意图分类 + 混合策略）
│   └── prompts.py                      # SYSTEM_PROMPT（5 工具 + 8 示例）+ PLAN_PROMPT
├── tools/
│   ├── registry.py                     # 工具注册器
│   ├── multi_platform_tools.py         # 3 个文本搜索工具 + LLM IT3C 属性解析
│   ├── image_search_tools.py           # 图片搜索工具
│   ├── semantic_search_tool.py 🆕      # 语义推荐工具
│   └── __init__.py
├── platforms/
│   ├── platform_config.py              # 4 平台静态配置
│   ├── platform_database.py            # 单平台 DB（17 列 CRUD + 6 维评分 + 处理器别名）
│   ├── parallel_agent.py               # 多平台并行查询
│   └── __init__.py
├── database/
│   ├── connection.py                   # 线程安全 SQLite 连接
│   └── models.py                       # 会话/消息模型（商品统一走 platforms）
├── templates/index.html                # SPA 前端
├── static/
│   ├── css/style.css
│   ├── js/app.js
│   └── uploads/
├── tests/
│   ├── eval_helpers.py                 # 评估基础设施
│   ├── eval_p0_unit.py                 # P0 单元测试（43 case）
│   ├── eval_p1_parse.py                # P1 属性解析（17 case）
│   ├── eval_p2_e2e.py                  # P2 端到端（17 case）
│   ├── eval_p3_boundary.py             # P3 能力边界（15 case）
│   ├── eval_p5_optimization.py         # P5 优化验证（13 case）
│   ├── eval_p6_image.py                # P6 图片搜索（7 case）
│   ├── eval_it3c.py 🆕                 # IT3C 行业优化评估（46 case）
│   ├── eval_p4_benchmark.py            # P4 汇总
│   └── eval_results/
├── requirements.txt
├── .env                                # API 密钥 + 模型配置
├── .env.example
├── README.md
├── 需求文档.md
├── 优化文档.md
├── 评估文档.md
├── IT3C行业优化文档.md 🆕              # IT3C 优化方案（6 Phase）
├── IT3C问题复盘-产品视角.md 🆕          # 7 个 Case 的产品视角复盘
└── MULTI_PLATFORM_README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API

编辑 `.env`：

```env
# DeepSeek API（文本模型）
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_MODEL_PLAN=deepseek-v4-flash
DEEPSEEK_MODEL_SYNTHESIZE=deepseek-v4-flash
DEEPSEEK_MODEL_PARSE=deepseek-v4-flash

# 视觉模型（豆包，未更换）
ARK_VISION_MODEL=doubao-seed-2-0-pro-260215
```

### 3. 启动

```bash
python3 app.py
```

访问 **http://127.0.0.1:5001**

## 工具说明

5 个工具均通过 `@register_tool` 装饰器注册。

### 1. `multi_platform_price_comparison`
在京东、淘宝、拼多多、苏宁 4 个平台并行比价。支持 LLM 自动解析颜色/内存/处理器/预算等属性。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `product_name` | string | 是 | 商品名称 |
| `color` | string | 否 | 颜色筛选 |
| `memory` | string | 否 | 内存筛选 |

### 2. `query_single_platform_product`
查询指定平台的商品。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `platform_id` | string | 是 | jd / taobao / pdd / suning |
| `product_name` | string | 是 | 商品名称 |
| `color` | string | 否 | 颜色筛选 |
| `memory` | string | 否 | 内存筛选 |

### 3. `get_all_platform_products`
并行获取 4 个平台的所有商品列表，无需参数。

### 4. `search_product_by_image`
上传商品图片，多模态 LLM 识别后自动比价。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image_url` | string | 是 | 图片 URL |
| `color` | string | 否 | 颜色偏好 |
| `memory` | string | 否 | 容量偏好 |

### 5. `semantic_product_search` 🆕
根据使用场景、预算、品牌、处理器等条件推荐商品。适用于推荐型查询。

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `use_case` | string | "" | gaming/photography/battery/business/student/budget/flagship |
| `brand` | string | "" | Apple/小米/华为 等 |
| `processor_brand` | string | "" | sd(骁龙)/mt(天玑)/apple(A/M)/kirin(麒麟) |
| `performance_tier` | string | "" | flagship/mid/budget |
| `budget_max` | number | null | 最高预算 |
| `budget_min` | number | null | 最低预算 |
| `category` | string | "手机" | 品类 |
| `sort_by` | string | "value" | value(性价比)/price(最低价)/performance(性能优先) |
| `top_n` | integer | 5 | 返回条数 |

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web 界面 |
| `/api/chat` | POST | 聊天接口 |
| `/api/image-search` | POST | 图片搜索 |
| `/api/upload-image` | POST | 图片上传 |
| `/api/sessions` | GET/POST | 会话列表 / 创建 |
| `/api/sessions/<id>` | DELETE | 删除会话 |
| `/api/sessions/<id>/messages` | GET | 会话消息 |
| `/api/products` | GET/POST | 商品聚合（多平台去重）/ 添加 |
| `/api/multi-platform/compare` | POST | 直接比价 |
| `/api/multi-platform/products` | GET | 所有平台商品 |
| `/api/platforms` | GET | 平台列表 |
| `/api/platforms/<pid>/products` | GET/POST | 平台商品 / 添加 |
| `/api/platforms/<pid>/products/<id>` | PUT/DELETE | 更新 / 删除 |

## 数据库设计

### 平台数据库（`platform_{jd/taobao/pdd/suning}.db`）

```sql
CREATE TABLE products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name    TEXT NOT NULL,
    price           REAL NOT NULL,
    stock           INTEGER NOT NULL,
    category        TEXT NOT NULL,
    platform_price  REAL,
    shipping_fee    REAL DEFAULT 0,
    is_in_stock     BOOLEAN DEFAULT 1,
    color           TEXT,
    memory          TEXT,
    -- 🆕 IT3C 扩展字段
    brand           TEXT,              -- 品牌：Apple/小米/华为
    processor       TEXT,              -- 处理器型号：A16 Bionic/骁龙8Gen3
    processor_brand TEXT,              -- 处理器厂商归一化：sd/mt/apple/kirin
    performance_tier TEXT,             -- 性能层级：flagship/mid/budget
    screen_size     REAL,              -- 屏幕尺寸（寸）
    battery         INTEGER,           -- 电池容量（mAh）
    use_case_tags   TEXT,              -- JSON 数组：["gaming","photography"]
    description     TEXT               -- 简短介绍
);
```

### 会话数据库（`price_agent.db`）

```sql
CREATE TABLE sessions (id, session_id, created_at);
CREATE TABLE messages (id, session_id, role, content, timestamp);
```

## 配置说明

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|--------|------|
| API Key | `DEEPSEEK_API_KEY` | - | DeepSeek API 密钥 |
| 默认模型 | `DEEPSEEK_MODEL` | deepseek-v4-flash | ReAct 循环 + Plan-Execute |
| Plan 模型 | `DEEPSEEK_MODEL_PLAN` | deepseek-v4-flash | Phase 1 计划生成 |
| 综合模型 | `DEEPSEEK_MODEL_SYNTHESIZE` | deepseek-v4-flash | Phase 3 综合分析 |
| 解析模型 | `DEEPSEEK_MODEL_PARSE` | deepseek-v4-flash | 属性提取 |
| 视觉模型 | `ARK_VISION_MODEL` | doubao-seed-2-0-pro | 图片识别（豆包） |
| 最大推理轮数 | - | 5 | ReAct 循环上限 |
| Plan 最大步数 | - | 8 | 执行计划步骤上限 |
| 历史窗口轮数 | - | 6 | 滑动窗口保留轮数 |
| 历史窗口字符 | - | 6000 | 滑动窗口字符上限 |

## 评估体系

9 阶段评估，151+ 测试 case，含新增 IT3C 行业优化专项。

```bash
python3 tests/eval_p0_unit.py            # P0 单元（43 case）
python3 tests/eval_p1_parse.py           # P1 属性解析（17 case）
python3 tests/eval_p2_e2e.py             # P2 端到端（17 case）
python3 tests/eval_p3_boundary.py        # P3 能力边界（15 case）
python3 tests/eval_p5_optimization.py    # P5 优化验证（13 case）
python3 tests/eval_p6_image.py           # P6 图片搜索（7 case）
python3 tests/eval_it3c.py               # IT3C 评估（35 case P0 单元）
python3 tests/eval_it3c.py --all         # IT3C 评估（46 case 全部，含 LLM）
python3 tests/eval_p4_benchmark.py       # P4 汇总
```

### 最新结果（2026-05-12，DeepSeek V4 Flash）

| 阶段 | 通过率 | 说明 |
|------|:------:|------|
| P0 单元测试 | 97.7% (42/43) | 1 项为 DROP+CREATE 预期行为 |
| P1 参数提取 | 100% (17/17) | 属性 + 别名 |
| P2 端到端 | 100% (17/17) | ReAct + Plan-Execute |
| P3 能力边界 | 100% (15/15) | 异常输入全正确处理 |
| P5 优化验证 | 100% (13/13) | 自反思 / Prompt / 路由 |
| P6 图片搜索 | 100% (7/7) | 识别 → 比价 |
| **IT3C P0** 🆕 | **100% (35/35)** | 语义搜索 / 意图分类 / deref / 处理器别名 |
| **IT3C P1** 🆕 | **100% (7/7)** | IT3C 属性提取（use_case/budget/processor_brand/tier） |
| **IT3C P2** 🆕 | **100% (4/4)** | 端到端推荐链路 |
| **综合** | **99.3% (151/152)** | |

### 各维度指标

| 维度 | 得分 | 说明 |
|------|:----:|------|
| 基础功能正确率 | 97.7% | P0 |
| 参数提取准确率 | 100% | 属性 + 别名 + IT3C |
| 答案正确率 | 100% | 全部正确 |
| 幻觉率 | 0% | 无 |
| 优雅降级率 | 100% | 异常输入全处理 |
| 意图分类准确率 | 100% | 14/14 包括处理器查询 |
| 推荐工具过滤正确率 | 100% | 10/10 过滤 + 排序 |

## 技术栈

- **Python 3.10+**
- **DeepSeek V4 Flash** — 文本模型（OpenAI 兼容 API）
- **豆包 Doubao** — 视觉模型
- **Flask** — Web 框架
- **SQLite** — 数据存储
- **ThreadPoolExecutor** — 多平台并行 + Plan-Execute 并行

## 许可证

MIT License
