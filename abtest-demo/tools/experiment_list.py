"""列出所有可用的 AB 实验。"""

from .registry import register_tool
from .data import ALL_EXPERIMENTS


@register_tool(
    name="get_experiment_list",
    schema={
        "type": "function",
        "function": {
            "name": "get_experiment_list",
            "description": "列出所有可用的 AB 实验及其基本信息（名称、状态、周期、样本量、主指标）。当用户不确定要分析哪个实验时先调用此工具。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
)
def get_experiment_list() -> dict:
    return {"experiments": ALL_EXPERIMENTS, "total": len(ALL_EXPERIMENTS)}
