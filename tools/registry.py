from typing import Dict, Callable, Any


class ToolRegistry:
    """工具注册器"""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, func: Callable, schema: Dict[str, Any]):
        """
        注册工具
        :param name: 工具名称
        :param func: 工具函数
        :param schema: OpenAI工具Schema
        """
        self._tools[name] = {
            "func": func,
            "schema": schema
        }

    def get_func(self, name: str) -> Callable:
        """获取工具函数"""
        return self._tools[name]["func"]

    def get_schemas(self) -> list:
        """获取所有工具的Schema列表"""
        return [tool["schema"] for tool in self._tools.values()]

    def get_tool_map(self) -> Dict[str, Callable]:
        """获取工具名称到函数的映射"""
        return {name: tool["func"] for name, tool in self._tools.items()}


# 全局工具注册器实例
tool_registry = ToolRegistry()


def register_tool(name: str, schema: Dict[str, Any]):
    """
    工具注册装饰器
    :param name: 工具名称
    :param schema: OpenAI工具Schema
    """
    def decorator(func: Callable):
        tool_registry.register(name, func, schema)
        return func
    return decorator
