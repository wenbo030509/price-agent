---
name: rag_knowledge
description: 知识库评测 — 检索商品评测和知识库信息增强回答
tools:
  - search_product_knowledge
user_invocable: true
disable_model_invocation: false
priority: 6
triggers:
  - 评测
  - 对比
  - 芯片
  - 处理器
  - 哪个好
  - 值得买
  - 为什么
  - 怎么样
  - 性能
  - 拍照好
  - 散热
  - 续航能力
  - 选哪个
  - 区别
  - 差距
  - 优势
  - 劣势
depends_on: []
---

你正在检索商品评测和知识库信息以增强回答。

## 知识检索行为规则

- 在先调用比价/推荐工具获取商品数据后，再根据用户追问调用本工具
- 综合商品数据 + 知识库内容给出最终回答
- 知识库返回空结果时，直接告知用户"暂未收录该信息"，不要编造

## 工具选择指南

### search_product_knowledge
**什么情况下用：**
- 用户问芯片性能对比 → "骁龙8Gen3 和 A17 Pro 哪个打游戏好"
- 用户问机型评测 → "小米14 拍照真的比 iPhone 15 强吗"
- 用户问处理器水平 → "天玑9300 是什么级别的芯片"
- 在推荐商品后，用户追问"为什么推荐这款" → 检索评测知识增强解释

**什么情况下不要用：**
- 用户只需要查价格 → 用 multi_platform_price_comparison
- 用户只需要推荐商品 → 用 semantic_product_search
- 知识库返回空结果 → 直接告知用户"暂未收录该信息"，不要编造

**使用策略：**
- 先调用其他工具（multi_platform_price_comparison / semantic_product_search）获取商品数据
- 再根据用户追问调用本工具检索评测/对比知识
- 综合商品数据 + 知识库内容给出最终回答
