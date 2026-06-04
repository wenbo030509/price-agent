"""
工具注册器 — 与 price-agent tools/registry.py 同模式。
使用 @register_tool 装饰器将工具函数和 OpenAI function schema 绑定注册。
"""

import numpy as np
from typing import Dict, Callable, Any


class ToolRegistry:
    """工具注册器"""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, func: Callable, schema: Dict[str, Any]):
        self._tools[name] = {"func": func, "schema": schema}

    def get_schemas(self) -> list:
        return [t["schema"] for t in self._tools.values()]

    def get_tool_map(self) -> Dict[str, Callable]:
        return {name: t["func"] for name, t in self._tools.items()}


tool_registry = ToolRegistry()


def register_tool(name: str, schema: Dict[str, Any]):
    """工具注册装饰器"""

    def decorator(func: Callable):
        tool_registry.register(name, func, schema)
        return func

    return decorator


def _py(v):
    """Convert numpy types to native Python for JSON serialization."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v
