# rag_tool — RAG 知识检索工具

## 概述

RAG（Retrieval-Augmented Generation）知识检索工具，将手机领域知识库（处理器性能对比、机型评测、参数规格）注册为 Agent 可调用的工具。

该模块是知识库的**工具注册层**，底层检索逻辑由 [knowledge_indexer.py](knowledge_indexer.md) 提供。

## 注册的工具

### `search_product_knowledge`

| 属性 | 值 |
|------|-----|
| **名称** | `search_product_knowledge` |
| **用途** | 检索手机领域知识库，获取处理器对比、机型评测、参数规格 |
| **必填参数** | `query` - 自然语言查询 |
| **可选参数** | `knowledge_type` - 知识类型过滤（默认 `auto`）；`top_k` - 返回条数（默认 3） |

### 参数说明

#### `query` (必填)

自然语言查询，例如：
- "骁龙8Gen3 和 A17 Pro 哪个好"
- "小米14 拍照怎么样"
- "这个处理器什么水平"

#### `knowledge_type` (可选)

| 值 | 对应目录 | 说明 |
|-----|----------|------|
| `auto` | 全部 | 不限制知识类型 |
| `chipset_compare` | `processors/` | 芯片性能对比 |
| `phone_review` | `reviews/` | 机型评测 |
| `spec_lookup` | `specs/` | 参数规格查询 |

#### `top_k` (可选)

返回的知识条数，默认 3。

## 初始化

### `init_knowledge_retriever(industry: str = "mobile")`

在应用启动时（`app initialize()`）调用，完成：

1. 创建 `KnowledgeIndexer`，遍历 `knowledge/<industry>/` 下的 Markdown 文件
2. 调用 `indexer.index_all()` 进行分块和 Embedding 预热
3. 创建 `KnowledgeRetriever` 并赋值给全局变量 `_retriever`

```python
# 在 app initialize() 中调用
from tools.rag_tool import init_knowledge_retriever
init_knowledge_retriever("mobile")
```

## 与比价工具的区别

| | `search_product_knowledge` | `multi_platform_price_comparison` |
|------|------|------|
| **返回内容** | 评测/参数/处理器知识 | 商品价格 |
| **数据来源** | `knowledge/` 下的 Markdown 文件 | 电商平台数据库（mock） |
| **检索方式** | BM25 + 语义混合检索 | 数据库属性查询 |
| **适用场景** | "骁龙8Gen3 性能如何" | "iPhone 15 多少钱" |

## 依赖

- [knowledge_indexer.py](knowledge_indexer.md) - 底层索引和检索
- `.registry.register_tool` - 工具注册装饰器
