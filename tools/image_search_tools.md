# image_search_tools — 图片识物比价工具

## 概述

根据用户上传的商品图片，通过多模态 LLM 自动识别商品属性（名称、颜色、品牌、品类），然后跨平台搜索同款/相似商品的价格。

## 注册的工具

### `search_product_by_image`

| 属性 | 值 |
|------|-----|
| **名称** | `search_product_by_image` |
| **用途** | 根据商品图片跨平台搜同款比价 |
| **必填参数** | `image_url` - 商品图片的 URL 地址 |
| **可选参数** | `color` - 用户额外指定的颜色偏好；`memory` - 用户额外指定的内存/容量偏好 |

## 处理流程

```
图片 URL
  │
  ▼
_ensure_base64()         # 远程 URL → base64 data URL（解决火山 API 访问限制）
  │
  ▼
_extract_attrs_from_image()  # 多模态 LLM：图片 → 结构化属性 JSON
  │                           # 输出: {product_name, color, category, brand, confidence}
  ▼
search_product_by_image()    # 属性 → multi_platform_price_comparison 文本搜索
  │
  ▼
返回: image_attrs + search_query + comparison + formatted_text
```

## 核心函数

### `_ensure_base64(image_url: str) -> str`

- 如果 `image_url` 是远程 HTTP URL，下载并转为 base64 data URL
- 如果已经是 `data:` URL 则直接返回
- 如果下载失败，回退到原始 URL（让 API 服务器自己尝试）
- 自动推断 MIME 类型（jpg/jpeg/png/webp/gif）

### `_extract_attrs_from_image(image_url, client, model) -> Dict`

- 使用多模态 LLM（视觉模型，如豆包）从图片提取商品结构化属性
- Prompt 要求输出纯 JSON，包含 `product_name`、`color`、`category`、`brand`、`confidence` 五个字段
- 图片中有多个商品时，只识别最主要/最突出的那个
- 识别失败时所有字段为空字符串，`confidence` 为 `low`

### `_get_vision_client()`

- 获取多模态识别的 client 和 model
- 从 `config.Settings` 读取 `model_vision` 配置

## 识别置信度处理

| confidence | 处理方式 |
|------------|----------|
| `high` / `medium` | 正常搜索，结果直接返回 |
| `low` | 仍然执行搜索，但返回结果中追加 `warning` 提示用户图片识别可能不准 |

## 多模型路由

- **视觉识别**：使用 `model_vision`（豆包多模态模型）
- **文本搜索**：走 `multi_platform_price_comparison` 的文本链路（DeepSeek V4 Flash）

## 依赖

- `openai` - OpenAI 兼容客户端
- `ssl` + `urllib.request` - 图片下载
- `base64` - 图片编码
- `platforms.PlatformParallelAgent` - 多平台比价引擎
- `.registry.register_tool` - 工具注册装饰器
