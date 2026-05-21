# semantic_search_tool — 语义推荐工具

## 概述

根据使用场景、预算、品牌、处理器等条件，通过向量召回 + 规则过滤的混合检索方式推荐商品。支持性价比、最低价、性能三种排序方式。

该模块是 M2（语义召回升级）的核心实现。

## 注册的工具

### `semantic_product_search`

| 属性 | 值 |
|------|-----|
| **名称** | `semantic_product_search` |
| **用途** | 根据场景/预算/品牌/处理器等条件语义推荐商品 |
| **必填参数** | 无（全部可选） |
| **可选参数** | 见下方参数表 |

#### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `use_case` | `str` | `""` | 场景标签：gaming/photography/battery/business/student/budget/flagship |
| `brand` | `str` | `""` | 品牌偏好：Apple/小米/华为 等 |
| `processor_brand` | `str` | `""` | 处理器厂商：sd/mt/apple/kirin |
| `performance_tier` | `str` | `""` | 性能层级：flagship/mid/budget |
| `budget_max` | `float` | `None` | 最高预算（元） |
| `budget_min` | `float` | `None` | 最低预算（元） |
| `category` | `str` | `"手机"` | 品类 |
| `sort_by` | `str` | `"value"` | 排序：value=性价比 / price=最低价 / performance=性能 |
| `top_n` | `int` | `5` | 返回推荐数量 |

#### 返回值

```json
{
  "success": true,
  "total_found": 25,
  "recommendations": [
    {
      "rank": 1,
      "product_name": "iPhone 15 Pro",
      "brand": "Apple",
      "price": 7999,
      "platform": "京东",
      "processor": "A17 Pro",
      "performance_tier": "flagship",
      "use_case_tags": "gaming,photography",
      "description": "...",
      "value_score": 12.5
    }
  ],
  "filter_summary": "品类=手机, 预算=不限-5000, 场景=gaming, 排序=value"
}
```

## 处理流程

```
Step 1: 聚合候选商品
  PlatformParallelAgent.query_all_products_parallel() → 去重（同名保留最低价）
  │
Step 2: 向量召回（enable_vector_recall=true 时）
  构造 query_text → embedding → cosine similarity → top-50
  │
Step 3: 规则过滤
  category / budget_max/min / brand / processor_brand / performance_tier / use_case
  │
  ├── 向量+规则混合模式: 向量结果优先 → 规则补充去重
  └── 纯规则模式: 直接过滤（enable_vector_recall=false）
  │
Step 4: 排序
  value_score = tier / price * 10000 （性价比）
  │
Step 5: 格式化返回
```

## 核心函数

### `build_product_text(product, fields) -> str`

将商品的结构化字段拼接为自然语言文本，用于 Embedding 计算：

```
商品名：iPhone 15 Pro 黑色 256GB
品牌：Apple
描述：A17 Pro芯片，钛金属机身，专业摄像
场景标签：gaming, photography, flagship
处理器：A17 Pro
```

### `_vector_recall(query, products, embedding_fields, top_k=50) -> List[dict]`

向量召回流程：

1. Query Embedding
2. Product Embedding（优先从全局缓存 `_product_embedding_cache` 读取）
3. Cosine Similarity 计算
4. Top-K 排序返回

### `_value_score(item, sort_by) -> float`

| sort_by | 计算公式 | 说明 |
|---------|----------|------|
| `value` | `tier / price * 10000` | 性价比 = 性能分 / 价格 |
| `price` | `-price` | 价格越低排越前 |
| `performance` | `tier` | 纯性能排序 |

## 配置开关

| 配置项 | 位置 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_vector_recall` | `industry_config` | `false` | 启用向量召回（关闭则纯规则模式） |
| `embedding_fields` | `industry_config` | `[]` | 参与 embedding 的商品字段列表 |

## Embedding 缓存

- 启动时由 `init_product_embeddings()` 预热所有商品 embedding
- 运行时通过 `get_cached_embedding()` 从缓存获取
- 缓存未命中时实时计算并回填 `_product_embedding_cache`

## 与比价工具的区别

| | `semantic_product_search` | `multi_platform_price_comparison` |
|------|------|------|
| **目的** | 推荐筛选（"帮我挑"） | 精确比价（"哪里便宜"） |
| **输入** | 场景/预算等模糊条件 | 明确商品名称 |
| **输出** | Top-N 推荐列表 | 各平台价格对比 |
| **排序** | 性价比/性能/价格 | 价格最低 |
| **召回方式** | 向量+规则混合 | 数据库属性精确匹配 |

## 依赖

- `numpy` - 向量数学
- `platforms.PlatformParallelAgent` - 商品数据获取
- `config.load_industry_config` / `config.Settings` - 配置与 Embedding 客户端
- `.registry.register_tool` - 工具注册
