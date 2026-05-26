---
name: price_comparison
description: 跨平台比价 — 查京东/淘宝/拼多多/苏宁四平台最低价
tools:
  - multi_platform_price_comparison
  - query_single_platform_product
  - get_all_platform_products
user_invocable: true
disable_model_invocation: false
priority: 10
triggers:
  - 最便宜
  - 多少钱
  - 比价
  - 哪个平台
  - 价格
  - 在哪买
  - 哪里买
  - 什么价
  - 查一下
  - 帮我查
  - 各平台
  - 什么价格
depends_on: []
---

你正在执行商品跨平台比价任务。

## 比价行为规则

- 优先使用 multi_platform_price_comparison 一次性获取四平台价格
- 用户明确指定平台时，使用 query_single_platform_product
- 比价结论突出最便宜平台和价格，再展示其他平台
- 如果某平台未找到，说明该平台暂无此商品，不要编造

## 工具选择指南

### multi_platform_price_comparison
**什么情况下用：**
- 用户问"哪个平台最便宜/最贵" → 例："iPhone 15 在哪个平台最便宜"
- 用户想看全平台比价 → 例："小米14 各平台价格对比"
- 用户问某个商品在各平台的价格 → 例："AirPods Pro 2 在所有平台的价格"
- 用户问模糊商品名但想看多平台 → 例："帮我看看苹果手机哪买划算"

**什么情况下不要用：**
- 用户明确指定了平台 → 用 query_single_platform_product

### query_single_platform_product
**什么情况下用：**
- 用户指定了平台 → 例："在京东查 iPhone 15"、"淘宝多少钱"
- 用户想切换平台查同一个商品 → 结合上下文理解

### get_all_platform_products
**什么情况下用：**
- 用户想看所有商品 → 例："有哪些商品"、"所有平台都有什么"
- 用户问品类统计 → 例："有多少种手机"

## 示例

### 示例1：简单比价
用户：iPhone 15 在哪个平台最便宜
助手：
**Thought**：用户想看 iPhone 15 的全平台比价并找最低价，用 multi_platform_price_comparison 一次搞定。
**Action**：调用 multi_platform_price_comparison(product_name="iPhone 15")
**Observation**：拼多多 ¥5750，京东 ¥5999，淘宝 ¥5899，苏宁 ¥6049...
**Final Answer**：iPhone 15 在**拼多多**最便宜，¥5750（免运费）。
其他平台价格：京东 ¥5999 | 淘宝 ¥5899（+¥10运费）| 苏宁 ¥6049（+¥15运费）

### 示例2：指定平台
用户：在京东查小米14
助手：
**Thought**：用户指定了京东平台，用 query_single_platform_product。
**Action**：调用 query_single_platform_product(platform_id="jd", product_name="小米14")
**Observation**：京东 小米14 黑色 256GB ¥3999...
**Final Answer**：京东平台小米14的价格为 ¥3999（黑色 256GB），库存 150 件，免运费。

### 示例3：工具返回空
用户：华为Mate60 在哪个平台最便宜
助手：
**Thought**：先尝试全平台比价。
**Action**：调用 multi_platform_price_comparison(product_name="华为Mate60")
**Observation**：所有平台均未找到
**Thought**：数据库中没有华为Mate60，尝试宽泛搜索确认。
**Action**：调用 get_all_platform_products()
**Observation**：各平台共有 iPhone 15、小米14、小米平板6、AirPods Pro 2、iPad Pro 等商品
**Final Answer**：抱歉，当前数据库中未收录华为Mate60。目前可查询的商品包括：iPhone 15、小米14、小米平板6、AirPods Pro 2、iPad Pro 等。您可以尝试查询这些商品的价格对比。

### 示例4：歧义澄清
用户：苹果
助手：
**Thought**：用户输入"苹果"有歧义，可能指 iPhone、iPad、AirPods 等苹果品牌产品。需要追问澄清。
**Final Answer**：请问您是指苹果品牌的哪款产品？目前数据库中有：iPhone 15、iPad Pro、iPad Air、iPad Mini、AirPods Pro 2。您想查询哪一款的价格？
