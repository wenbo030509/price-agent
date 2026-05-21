"""pytest fixtures — 为 test_embedding / test_m3_rag / test_m5_shopping 提供共享依赖。

这些测试原本采用脚本式 "return 值传递" 模式（test_a 返回对象给 test_b），
pytest 不支持。本文件补全对应的 session-scoped fixture，使 pytest 能正常解析。
"""
import os
import pytest
from dotenv import load_dotenv

load_dotenv()


# ══════════════════════════════════════════════════════════════════
# EmbeddingClient — test_embedding.py（6 个测试）
# ══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def client():
    """火山引擎 ARK EmbeddingClient，供 test_embedding.py 使用"""
    ark_key = os.getenv("ARK_API_KEY")
    if not ark_key:
        pytest.skip("ARK_API_KEY not configured in .env")

    from config.embedding import EmbeddingClient
    return EmbeddingClient(
        api_key=ark_key,
        model=os.getenv("ARK_EMBEDDING_MODEL", "doubao-embedding-vision-251215"),
        base_url=os.getenv("ARK_EMBEDDING_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
    )


# ══════════════════════════════════════════════════════════════════
# KnowledgeIndexer / KnowledgeRetriever — test_m3_rag.py（3 个测试）
# ══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def indexer(client):
    """KnowledgeIndexer，已执行 index_all()，供 test_m3_rag.py 使用"""
    from tools.knowledge_indexer import KnowledgeIndexer

    idx = KnowledgeIndexer("mobile")
    idx.index_all()
    return idx


@pytest.fixture(scope="session")
def retriever(indexer):
    """KnowledgeRetriever，基于 indexer 构建，供 test_m3_rag.py 使用"""
    from tools.knowledge_indexer import KnowledgeRetriever
    return KnowledgeRetriever(indexer)


# ══════════════════════════════════════════════════════════════════
# ReActAgent — test_m5_shopping.py（3 个测试）
# ══════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def agent():
    """ReActAgent 完整实例，供 test_m5_shopping.py 使用"""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if not deepseek_key:
        pytest.skip("DEEPSEEK_API_KEY not configured in .env")

    from config import Settings
    from tools import tool_registry, init_parallel_agent
    from platforms import init_all_platforms
    from agent import ReActAgent

    # 平台和并行 Agent 只初始化一次（模块内部有幂等检查）
    init_all_platforms()
    init_parallel_agent()

    s = Settings()
    return ReActAgent(
        client=s.client,
        model=s.model,
        tools=tool_registry.get_schemas(),
        tool_map=tool_registry.get_tool_map(),
        config={
            "industry_config": s.industry_config,
            "max_history_rounds": 5,
            "max_history_chars": 1000,
            "max_reflection_retries": 0,
            "auto_relax_attributes": False,
            "max_step_react_rounds": 2,
            "max_plan_steps": 3,
        },
    )
