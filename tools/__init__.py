from .registry import ToolRegistry, register_tool, tool_registry
from .multi_platform_tools import *
from . import image_search_tools  # 注册图片搜索工具
from . import semantic_search_tool  # 注册语义推荐工具
from . import rag_tool  # M3: 注册 RAG 知识检索工具

__all__ = [
    "ToolRegistry",
    "register_tool",
    "tool_registry",
    "init_parallel_agent",
    "get_parallel_agent",
    "cleanup_parallel_agent",
]
