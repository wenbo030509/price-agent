# registry — 工具注册器

## 概述

提供基于装饰器的工具注册机制，为 Agent 引擎提供统一的工具发现和调用接口。

## 架构

```
@register_tool(name, schema)
  │
  ▼
ToolRegistry
  ├── register(name, func, schema)
  │     将工具函数和 Schema 存储到 _tools 字典
  │
  ├── get_func(name) → Callable
  │     按名称获取工具函数
  │
  ├── get_schemas() → list[dict]
  │     获取所有工具的 OpenAI Function Schema 列表
  │     用于提交给 LLM 作为 tools 参数
  │
  └── get_tool_map() → Dict[str, Callable]
        获取名称→函数的映射
        用于 tool_calls 结果分发
```

## 类说明

### `ToolRegistry`

全局工具注册表单例，管理所有已注册工具。

#### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `_tools` | `Dict[str, Dict]` | `{name: {"func": Callable, "schema": dict}}` |

#### 方法

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `register(name, func, schema)` | `None` | 注册一个工具 |
| `get_func(name)` | `Callable` | 按名称获取工具函数 |
| `get_schemas()` | `list[dict]` | 获取所有工具的 OpenAI Schema 列表 |
| `get_tool_map()` | `Dict[str, Callable]` | 获取名称到函数的映射 |

### `register_tool(name, schema)` (装饰器)

装饰器工厂函数，返回装饰器函数。使用方式：

```python
@register_tool(
    name="my_tool",
    schema={
        "type": "function",
        "function": {
            "name": "my_tool",
            "description": "工具描述",
            "parameters": {...}
        }
    }
)
def my_tool(param1: str, param2: int = 0) -> Dict:
    ...
```

装饰器会将函数及其 Schema 注册到全局 `tool_registry` 单例，同时保持原函数不变（可被其他模块直接调用）。

## 全局单例

```python
tool_registry = ToolRegistry()
```

所有通过 `@register_tool` 装饰器注册的函数都会被添加到这个唯一的 registry 实例中。

## 注册流程

1. 各工具模块在文件顶层使用 `@register_tool` 装饰器定义工具函数 → 装饰器执行时立即注册
2. `tools/__init__.py` 通过 import 所有子模块触发注册
3. Agent 引擎通过 `tool_registry.get_schemas()` 获取工具列表传给 LLM
4. LLM 返回 tool_calls 后，通过 `tool_registry.get_func(name)` 查找并调用对应函数

## 依赖

无外部依赖，纯 Python 标准库（`typing.Dict`, `typing.Callable`）。
