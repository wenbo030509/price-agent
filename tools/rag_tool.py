"""
tools/rag_tool.py
RAG 知识检索工具 — Agent 第 6 个工具，检索手机领域知识库。
"""
from typing import Dict, Optional
from .registry import register_tool

# 全局检索器实例（app 启动时初始化）
_retriever = None


def init_knowledge_retriever(industry: str = "mobile"):
    """在 app initialize() 中调用，初始化知识库索引和检索器"""
    global _retriever
    from tools.knowledge_indexer import KnowledgeIndexer, KnowledgeRetriever

    indexer = KnowledgeIndexer(industry)
    indexer.index_all()
    _retriever = KnowledgeRetriever(indexer)


@register_tool(
    name="search_product_knowledge",
    schema={
        "type": "function",
        "function": {
            "name": "search_product_knowledge",
            "description": (
                "检索手机领域知识库（处理器性能对比、机型评测、参数规格）。"
                "适用于：用户问'骁龙8Gen3和A17 Pro哪个好'、"
                "'小米14拍照怎么样'、'这个处理器什么水平'等需要专业知识的问题。"
                "注意：本工具返回的是评测/参数知识，不返回商品价格。"
                "查价格请用 multi_platform_price_comparison。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言查询，如 '骁龙8Gen3 游戏性能'、'小米14 拍照评测'",
                    },
                    "knowledge_type": {
                        "type": "string",
                        "description": (
                            "知识类型：chipset_compare(芯片对比) / phone_review(机型评测) / "
                            "spec_lookup(参数规格) / auto(自动判断)"
                        ),
                        "default": "auto",
                        "enum": ["auto", "chipset_compare", "phone_review", "spec_lookup"],
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回知识条数，默认 3",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        },
    },
)
def search_product_knowledge(
    query: str,
    knowledge_type: str = "auto",
    top_k: int = 3,
) -> Dict:
    if _retriever is None:
        return {
            "success": False,
            "error": "知识库未初始化",
            "references": [],
        }
    return _retriever.retrieve(query, knowledge_type, top_k)
