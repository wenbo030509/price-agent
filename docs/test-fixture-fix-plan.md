# 测试 Fixture 修复方案

## 问题总览

12 个测试因缺少 pytest fixture 报 ERROR（非 FAIL），分布在 3 个测试文件中。

## 根因分析

### 类别 1：test_embedding.py（6 个 ERROR）

| 测试 | 缺失 fixture | 原因 |
|------|-------------|------|
| test_single_text | `client` | 需要 `EmbeddingClient(api_key=...)` ，无 pytest fixture 定义 |
| test_parallel_batch | `client` | 同上 |
| test_batched_split | `client` | 同上 |
| test_dimension | `client` | 同上 |
| test_cosine_similarity | `client` | 同上 |
| test_product_recall_simulation | `client` | 同上 |

**根因**：测试函数签名写了 `def test_single_text(client)`，但项目中没有 `conftest.py` 定义 `client` fixture。这些测试最初作为脚本运行（手动创建 client 后调用），迁移到 pytest 时未补 fixture。

**阻断条件**：需要 `ARK_API_KEY` 环境变量或 `.env` 中的火山引擎 API Key。没有 API Key 时无法创建 `EmbeddingClient`。

### 类别 2：test_m3_rag.py（3 个 ERROR）

| 测试 | 缺失 fixture | 原因 |
|------|-------------|------|
| test_retrieval_quality | `indexer` | `KnowledgeIndexer` 需要 embedding 能力 |
| test_knowledge_type_filter | `indexer` | 同上 |
| test_tool_registration | `retriever` | `KnowledgeRetriever` 依赖 `KnowledgeIndexer` |

**根因**：这些测试采用了“返回值传递”模式——`test_index_and_chunk()` 返回 `indexer`，`test_retrieval_quality(indexer)` 期望接收这个返回值。但 pytest 不支持这种模式，return 值被忽略，`indexer` 参数被视为 fixture 名去查找。

`test_index_and_chunk` 可以独立通过，因为它不需要 fixture：
```python
def test_index_and_chunk():
    from tools.knowledge_indexer import KnowledgeIndexer
    indexer = KnowledgeIndexer("mobile")  # 自己创建
    indexer.index_all()
    return indexer  # ← 返回给谁？pytest 不接受
```

**阻断条件**：`KnowledgeIndexer` 内部需要 `EmbeddingClient` 来做向量化。如果 `DEEPSEEK_API_KEY` 和 `ARK_API_KEY` 都不可用，则无法创建 Indexer。

### 类别 3：test_m5_shopping.py（3 个 ERROR）

| 测试 | 缺失 fixture | 原因 |
|------|-------------|------|
| test_slot_extraction | `agent` | 需要 `ReActAgent` 实例 |
| test_guided_shopping_flow | `agent` | 同上 |
| test_followup_and_comparison | `agent` | 同上 |

**根因**：同类别 2，`test_intent_detection()` 内部创建了 agent 并 return，但 pytest 不传递返回值。

`test_intent_detection` 可以独立通过：
```python
def test_intent_detection():
    from config import Settings
    from tools import tool_registry, init_parallel_agent
    from platforms import init_all_platforms
    from agent import ReActAgent
    init_all_platforms()
    init_parallel_agent()
    s = Settings()
    agent = ReActAgent(client=s.client, model=s.model, ...)
    return agent  # ← 同样被 pytest 忽略
```

**阻断条件**：需要 `DEEPSEEK_API_KEY`。

---

## 修复方案

### 策略：新增 `tests/conftest.py` + `skipif` 标记

对所有 12 个受影响的测试：

1. **test_embedding.py — 6 个**：添加 `client` fixture，API key 不存在时 `pytest.skip`
2. **test_m3_rag.py — 3 个**：添加 `indexer` 和 `retriever` fixture，依赖 embedding 不可用时 skip
3. **test_m5_shopping.py — 3 个**：添加 `agent` fixture，API key 不存在时 skip

### conftest.py 设计

```python
# tests/conftest.py
import pytest
import os
from dotenv import load_dotenv

load_dotenv()

# ── Embedding client fixture ──
@pytest.fixture(scope="session")
def client():
    ark_key = os.getenv("ARK_API_KEY")
    if not ark_key:
        pytest.skip("ARK_API_KEY not configured")
    from config.embedding import EmbeddingClient
    return EmbeddingClient(api_key=ark_key)

# ── Knowledge indexer fixture ──
@pytest.fixture(scope="session")
def indexer(client):
    from tools.knowledge_indexer import KnowledgeIndexer
    indexer = KnowledgeIndexer("mobile")
    indexer.index_all()
    return indexer

# ── Knowledge retriever fixture ──
@pytest.fixture(scope="session")
def retriever(indexer):
    from tools.knowledge_indexer import KnowledgeRetriever
    return KnowledgeRetriever(indexer)

# ── ReActAgent fixture ──
@pytest.fixture(scope="session")
def agent():
    from config import Settings
    from tools import tool_registry, init_parallel_agent
    from platforms import init_all_platforms
    from agent import ReActAgent

    try:
        init_all_platforms()
        init_parallel_agent()
        s = Settings()
    except ValueError as e:
        pytest.skip(f"DEEPSEEK_API_KEY not configured: {e}")

    return ReActAgent(
        client=s.client,
        model=s.model,
        tools=tool_registry.get_schemas(),
        tool_map=tool_registry.get_tool_map(),
        config={"industry_config": s.industry_config},
    )
```

### 预期效果

| 场景 | 结果 |
|------|------|
| API Key 齐全 | 12 个之前 ERROR 的测试 → PASS 或 FAIL（业务逻辑问题），不再是 ERROR |
| 缺 ARK_API_KEY | 6 个 embedding 测试 skip，3 个 RAG 测试 skip，3 个 M5 测试正常运行 |
| 缺 DEEPSEEK_API_KEY | 3 个 M5 测试 skip，3 个 RAG 测试 skip（embedding 需要 DEEPSEEK 来向量化知识库） |
| 全缺 | 12 个全部 skip，0 个 ERROR |

### 不需要修改的测试

以下测试不需要 fixture，也不受影响：
- `test_m1_config.py` — 全部 8 个
- `test_m2_recall.py` — 全部 5 个
- `test_react_engine.py` — 全部 10 个
- `test_trace.py` — 全部 72 个
- `test_m3_rag.py::test_index_and_chunk` — 自己创建 indexer
- `test_m3_rag.py::test_regression` — 无 fixture
- `test_m3_rag.py::test_retriever_caching` — 无 fixture
- `test_m5_shopping.py::test_shopping_context` — 无 fixture
- `test_m5_shopping.py::test_intent_detection` — 自己创建 agent
- `test_m5_shopping.py::test_regression` — 无 fixture
