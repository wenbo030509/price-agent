# knowledge_indexer — 知识库索引与混合检索器

## 概述

自研的知识库索引和检索模块，读取 `knowledge/<industry>/` 目录下的 Markdown 文件，按 `##` 二级标题分块，通过 Embedding 预热向量缓存，提供 BM25 + 语义向量的混合检索能力。

该模块是 M3（RAG 知识增强）的核心底层实现。

## 架构

```
knowledge/mobile/
  ├── processors/  → source_dir="processors"  → knowledge_type="chipset_compare"
  ├── reviews/     → source_dir="reviews"     → knowledge_type="phone_review"
  └── specs/       → source_dir="specs"       → knowledge_type="spec_lookup"
```

## 类说明

### `KnowledgeIndexer`

索引器，负责读取 Markdown 文件、分块、生成 Embedding。

#### `__init__(self, industry: str = "mobile")`

- 初始化索引器
- `industry` 对应 `knowledge/` 下的子目录名
- `self.chunks` 为索引后的 chunk 列表

#### `index_all(self)`

遍历 `knowledge/<industry>/` 下所有 `.md` 文件，对每个文件：

1. 调用 `_chunk_file()` 分块
2. 所有 chunk 收集完成后调用 `_embed_chunks()` 批量生成 Embedding

#### `_chunk_file(self, filepath, source_dir) -> List[Dict]`

分块规则：

| 优先级 | 规则 | 说明 |
|--------|------|------|
| 1 | 按 `##` 标题分块 | 每个二级标题下的内容为一个独立 chunk |
| 2 | 跳过空块 | 长度 < 50 字符的块被丢弃 |
| 3 | 过长再切 | 单块超过 800 字符，按 `\n\n` 段落进一步切分 |

每个 chunk 包含字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `str` | chunk 文本内容 |
| `source` | `str` | 源文件名（如 `xiaomi14_review.md`） |
| `source_dir` | `str` | 源目录（`processors` / `reviews` / `specs`） |
| `section` | `str` | 对应的 `##` 标题文字 |
| `embedding` | `np.ndarray` | 2048 维浮点向量（`_embed_chunks` 填充） |

#### `_embed_chunks(self)`

- 批量调用 `embedding_client.embed_texts()` 生成所有 chunk 的向量
- 向量存储为 `np.float32` 类型

### `KnowledgeRetriever`

BM25 + 语义向量混合检索器。

#### `retrieve(self, query, knowledge_type="auto", top_k=5, alpha=0.7) -> Dict`

混合检索流程：

```
用户 query
  │
  ├─→ 语义检索（cosine similarity）
  │     query_vec · chunk_vec
  │     ─────────────────────  → 归一化到 [0,1]
  │     ‖query_vec‖·‖chunk_vec‖
  │
  ├─→ BM25 检索（Okapi BM25）
  │     中文按字符切分词
  │     → 归一化到 [0,1]
  │
  └─→ 融合: alpha * semantic + (1-alpha) * bm25
        alpha=0.7 语义为主，BM25 为辅
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `query` | 必填 | 自然语言查询 |
| `knowledge_type` | `"auto"` | 知识类型过滤：`chipset_compare` / `phone_review` / `spec_lookup` / `auto`（不过滤） |
| `top_k` | `5` | 返回条数 |
| `alpha` | `0.7` | 语义得分权重（0-1），越大语义比重越高 |

#### `_filter_by_type(self, chunks, knowledge_type) -> List[Dict]`

- `auto` → 返回全部 chunk
- `chipset_compare` → 过滤 `source_dir="processors"`
- `phone_review` → 过滤 `source_dir="reviews"`
- `spec_lookup` → 过滤 `source_dir="specs"`

## 依赖

- `numpy` - 向量数学运算
- `rank_bm25.BM25Okapi` - BM25 关键词检索
- `config.Settings().embedding_client` - Embedding 服务（豆包 doubao-embedding-vision-251215）
