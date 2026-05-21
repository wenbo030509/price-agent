# tools — 工具模块

Price Agent 的工具注册、多平台比价、图片搜索、语义推荐、RAG 知识检索等全部工具实现。

## 目录结构

```
tools/
├── README.md                   # 本文件
├── registry.py                 # 工具注册器（ToolRegistry + @register_tool 装饰器）
├── multi_platform_tools.py     # 多平台比价工具（京东/淘宝/拼多多/苏宁并行查询）
├── image_search_tools.py       # 图片识物比价工具（多模态 LLM → 文本搜索）
├── semantic_search_tool.py     # 语义推荐工具（向量召回 + 规则过滤混合检索）
├── rag_tool.py                 # RAG 知识检索工具（手机领域知识库）
├── knowledge_indexer.py        # 知识库索引器（Markdown 分块 + Embedding + BM25）
└── __init__.py                 # 模块导出，子模块自动注册
```

## 工具一览

| 工具名称 | 文件 | 用途 |
|----------|------|------|
| `multi_platform_price_comparison` | multi_platform_tools.py | 在京东/淘宝/拼多多/苏宁并行比价，支持颜色/内存精确筛选 |
| `query_single_platform_product` | multi_platform_tools.py | 查询指定平台单个商品信息 |
| `get_all_platform_products` | multi_platform_tools.py | 获取所有平台全部商品列表 |
| `search_product_by_image` | image_search_tools.py | 根据商品图片识别后跨平台搜同款比价 |
| `semantic_product_search` | semantic_search_tool.py | 根据场景/预算/品牌/处理器等条件语义推荐商品 |
| `search_product_knowledge` | rag_tool.py | 检索手机领域知识库（处理器对比、机型评测、参数规格） |

## 架构设计

### 注册机制

所有工具通过 [registry.py](registry.py) 中的 `@register_tool` 装饰器注册到全局 `tool_registry` 单例：

```python
@register_tool(name="tool_name", schema={...})
def my_tool(...):
    ...
```

`__init__.py` 在 import 时自动触发所有工具模块的注册。Agent 引擎通过 `tool_registry.get_schemas()` 获取全部工具 Schema，通过 `tool_registry.get_tool_map()` 获取名称到函数的映射。

### 数据流向

```
Agent 引擎
  │
  ├── tool_calls 解析
  │     │
  │     ▼
  │   tool_registry.get_func(name) → 调用工具函数
  │     │
  │     ▼
  │   PlatformParallelAgent
  │     │
  │     ├── PlatformDatabase (京东/淘宝/拼多多/苏宁)
  │     │
  │     └── 返回结构化结果
  │
  └── 结果注入 ReAct 循环
```

## 各模块详细说明

| 文件 | 详细说明 |
|------|----------|
| [registry.py](registry.py) | 工具注册装饰器与全局注册表单例 |
| [multi_platform_tools.py](multi_platform_tools.py) | 3 个比价工具 + LLM 属性解析，详见 [README](multi_platform_tools.md) |
| [image_search_tools.py](image_search_tools.py) | 图片下载/预处理 + 多模态识别 + 文本比价链路，详见 [README](image_search_tools.md) |
| [semantic_search_tool.py](semantic_search_tool.py) | 向量召回 + 规则过滤 + 性价比排序，详见 [README](semantic_search_tool.md) |
| [rag_tool.py](rag_tool.py) | RAG 工具注册 + 检索器初始化，详见 [README](rag_tool.md) |
| [knowledge_indexer.py](knowledge_indexer.py) | Markdown 分块 + Embedding + BM25 混合检索，详见 [README](knowledge_indexer.md) |
