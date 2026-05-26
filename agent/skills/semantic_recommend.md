---
name: semantic_recommend
description: 场景推荐 — 根据使用场景和预算智能推荐商品
tools:
  - semantic_product_search
user_invocable: true
disable_model_invocation: false
priority: 8
triggers:
  - 推荐
  - 建议
  - 适合
  - 哪款好
  - 什么手机
  - 选什么
  - 打游戏
  - 拍照
  - 续航
  - 商务
  - 学生
  - 性价比
  - 旗舰
  - 预算
  - 以内
  - 以下
  - 不超过
  - 骁龙
  - 天玑
depends_on: []
---

你正在根据用户场景和预算推荐商品。

## 推荐行为规则

- 优先调用 semantic_product_search 进行语义召回
- 用户有场景描述（游戏/拍照/续航等）但无具体型号时，用 use_case 参数过滤
- 用户有预算时，用 budget_max 参数限制
- 用户指定处理器品牌时，用 processor_brand 参数过滤
- 推荐结果按性价比排序（sort_by="value"），用户说"便宜"时按价格排序

## 工具选择指南

### semantic_product_search
**什么情况下用：**
- 用户描述使用场景而非具体型号 → 例："我经常打游戏，推荐什么手机"
- 用户给出预算范围 → 例："5000以内性价比最高的手机"
- 用户筛选处理器品牌 → 例："骁龙处理器的手机有哪些"
- 用户问"哪款好"但没给具体型号 → 例："拍照好的手机推荐一下"
- 含"推荐"/"适合"/"建议"/"什么手机"等词，且无明确型号

**什么情况下不要用：**
- 用户有明确型号（iPhone 15、小米14）→ 用 multi_platform_price_comparison 查价格
- 用户做两款机对比 → 用 multi_platform_price_comparison 分别查后对比

**参数填写规则：**
- use_case：从 gaming/photography/battery/business/student/budget/flagship 中选，多个用逗号分隔
- sort_by：用户说"便宜"→ price；用户说"性价比"→ value（默认）；用户说"最强"→ performance
- budget_max：从用户说的金额提取数字（"5000以内"→ 5000）
- 不确定的参数不传（默认不限）

## 示例

### 示例1：纯场景推荐
用户：我经常打游戏，推荐什么手机
助手：
**Thought**：推荐型需求，用户没给明确型号，只给了使用场景（gaming），用 semantic_product_search。
**Action**：调用 semantic_product_search(use_case="gaming", category="手机", sort_by="value")
**Observation**：推荐结果：①小米14（¥3999，骁龙8Gen3，性价比分250）②小米14 Pro（¥5299，骁龙8Gen3，性价比分151）③红米Note13（¥1299，天玑6080，性价比分269）...
**Final Answer**：游戏手机推荐（按性价比排序）：
🥇 **小米14**（¥3999）— 骁龙8Gen3，旗舰游戏性能，各平台最低价在拼多多 ¥3899
🥈 **小米14 Pro**（¥5299）— 骁龙8Gen3 + 更强散热，适合重度游戏用户
🥉 **iPhone 15 Pro**（¥8999）— A17 Pro，iOS生态游戏体验最佳，预算充足首选

### 示例2：预算 + 场景组合
用户：拍照好的手机，5000以内，推荐几款
助手：
**Thought**：推荐型需求，条件：use_case=photography + budget_max=5000。
**Action**：调用 semantic_product_search(use_case="photography", budget_max=5000, category="手机", sort_by="value")
**Observation**：过滤后找到：小米14（¥3999，徕卡影像）...
**Final Answer**：5000以内拍照手机推荐：
🥇 **小米14**（¥3999）— 徕卡联合调校，旗舰影像系统，拼多多 ¥3899
如果预算放宽到6000，还可以考虑 iPhone 15。

### 示例3：处理器筛选
用户：骁龙8Gen3处理器的手机有哪些
助手：
**Thought**：用户明确指定处理器，用 semantic_product_search 过滤 processor_brand=sd。
**Action**：调用 semantic_product_search(processor_brand="sd", category="手机")
**Observation**：找到：小米14（骁龙8Gen3）、小米14 Pro（骁龙8Gen3）...
**Final Answer**：搭载骁龙系列处理器的手机：
• **小米14**（¥3999）— 骁龙8Gen3，各平台最低价拼多多 ¥3899
• **小米14 Pro**（¥5299）— 骁龙8Gen3，旗舰散热
如需了解某款详细比价，告诉我商品名即可。
