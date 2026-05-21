# multi_platform_tools — 多平台比价工具

## 概述

提供京东、淘宝、拼多多、苏宁 4 个电商平台上的商品价格查询与对比能力。包含 3 个注册工具和 LLM 属性解析辅助，是 Price Agent 最核心的工具集。

## 注册的工具

### 1. `multi_platform_price_comparison`

| 属性 | 值 |
|------|-----|
| **名称** | `multi_platform_price_comparison` |
| **用途** | 在京东/淘宝/拼多多/苏宁并行查价，找出最低价 |
| **必填参数** | `product_name` - 商品名称，如 "iPhone 15" |
| **可选参数** | `color` - 颜色筛选；`memory` - 内存/容量筛选 |

**处理链路**：

```
product_name（可能含颜色/内存混写，如 "iPhone 15 黑色 256GB"）
  │
  ├─→ 检测是否需要 LLM 属性解析
  │     needs_parse = (没有显式传 color/memory) AND (product_name 含属性关键词)
  │
  ├─→ [如需解析] _parse_attrs_from_query()
  │     LLM 提取: product_name, brand, color, memory, category,
  │              processor_hint, processor_brand, use_case, budget_max, budget_min
  │
  └─→ PlatformParallelAgent.compare_product_price()
        → 4 平台并行查询 → 返回最低价结果
```

**属性关键词触发**：`product_name` 中包含 "黑"、"白"、"蓝"、"128"、"256"、"512"、"1T"、"GB" 等词时自动启用 LLM 解析。

### 2. `query_single_platform_product`

| 属性 | 值 |
|------|-----|
| **名称** | `query_single_platform_product` |
| **用途** | 查询指定平台单个商品信息 |
| **必填参数** | `platform_id`（jd/taobao/pdd/suning）、`product_name` |
| **可选参数** | `color`、`memory` |

直接调用 `PlatformDatabase.query_product_by_attrs()` 查询单个平台，不走并行引擎。

### 3. `get_all_platform_products`

| 属性 | 值 |
|------|-----|
| **名称** | `get_all_platform_products` |
| **用途** | 获取所有平台的全部商品列表 |
| **参数** | 无 |

调用 `PlatformParallelAgent.query_all_products_parallel()` 获取各平台全量商品。

## 核心函数

### `_parse_attrs_from_query(raw_query, llm_client, model) -> Dict`

使用 LLM（DeepSeek V4 Flash）从自然语言查询中提取结构化属性。

**提取字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `product_name` | `str` | 纯型号名（去掉颜色/内存/处理器修饰词） |
| `brand` | `str` | 品牌名（Apple/小米/华为/OPPO/vivo/三星/荣耀） |
| `color` | `str` | 颜色 |
| `memory` | `str` | 内存/容量 |
| `category` | `str` | 品类（手机/平板/耳机/电脑） |
| `processor_hint` | `str` | 处理器关键词（如"骁龙8Gen3"） |
| `processor_brand` | `str` | 处理器厂商归一化（sd/mt/apple/kirin） |
| `performance_tier` | `str` | 性能层级（flagship/mid/budget） |
| `use_case` | `str` | 使用场景标签 |
| `budget_max` | `float or None` | 最高预算（元） |
| `budget_min` | `float or None` | 最低预算（元） |

**品牌/别名标准化**：
- "水果手机"/"苹果手机"/"ip" 开头 → `brand="Apple"`
- "ip15"/"ip16" → `product_name="iPhone 15"/"iPhone 16"`
- "米14"/"mi14" → `product_name="小米14"`, `brand="小米"`

### `init_parallel_agent()` / `get_parallel_agent()`

全局单例 `PlatformParallelAgent` 的初始化和获取。

### `cleanup_parallel_agent()`

释放并行 agent 的资源。

## 依赖

- `openai.OpenAI` - LLM 客户端
- `platforms.PlatformParallelAgent` - 多平台并行查询引擎
- `platforms.format_comparison_result` - 比价结果格式化
- `.registry.register_tool` - 工具注册装饰器
- `config.Settings` - 配置（获取 `model_parse` 轻量模型）
