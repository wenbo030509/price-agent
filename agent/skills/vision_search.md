---
name: vision_search
description: 图片识别搜同款 — 上传商品图片搜同款并比价
tools:
  - search_product_by_image
user_invocable: true
disable_model_invocation: false
priority: 5
triggers:
  - 拍照
  - 图片
  - 照片
  - 扫一扫
  - 识别
  - 搜同款
  - 这个是什么
  - 看看这个
  - 上传
  - 图像
depends_on: []
---

你正在识别用户上传图片中的商品并搜索同款。

## 图片搜索行为规则

- 收到图片后优先调用 search_product_by_image 识别商品
- 识别结果包含商品名称和各平台价格，直接展示给用户
- 如果识别置信度低，提醒用户"可能需要输入商品名称精确搜索"
- 如果完全识别不出来，引导用户"请直接告诉我商品名称"
- 识别成功后，如果用户追问比价，切换到比价模式用 multi_platform_price_comparison

## 工具选择指南

### search_product_by_image
**什么情况下用：**
- 用户上传了商品图片 → 例：用户发了一张手机照片
- 用户说"拍照搜同款"、"帮我看看这个是什么"、"这个商品多少钱"
- 用户说"识别一下这个"、"扫一扫比价"

**流程：**
1. 先调用 search_product_by_image(image_url) 识别图片中的商品
2. 工具会自动在4个平台搜索并返回比价结果
3. 如果识别置信度低，提醒用户"可能需要输入商品名称精确搜索"
4. 如果完全识别不出来，引导用户"请直接告诉我商品名称"

## 示例

### 图片搜索
用户上传了一张黑色iPhone的图片，说"帮我看看这个手机在哪买最便宜"
助手：
**Thought**：用户上传了商品图片，需要用 search_product_by_image 识别图片中的商品。
**Action**：调用 search_product_by_image(image_url="<用户图片URL>")
**Observation**：识别到 iPhone 15 黑色，拼多多 ¥5750，京东 ¥5999...
**Final Answer**：图片识别为 **iPhone 15 黑色**（置信度：high）。
🏆 最便宜：拼多多 ¥5750（免运费）
其他平台：淘宝 ¥5899（+¥10运费）| 京东 ¥5999 | 苏宁 ¥6049（+¥15运费）
