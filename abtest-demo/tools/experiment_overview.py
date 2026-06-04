"""获取指定 AB 实验的完整信息（假设、设计参数、样本量充分性）。"""

from .registry import register_tool
from .data import EXPERIMENT, ALL_EXPERIMENTS


@register_tool(
    name="get_experiment_overview",
    schema={
        "type": "function",
        "function": {
            "name": "get_experiment_overview",
            "description": "获取指定 AB 实验的完整信息，包括实验假设、设计参数、样本量充分性分析。开始分析前必须调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string", "description": "实验 ID，默认推荐算法升级实验"},
                },
                "required": [],
            },
        },
    },
)
def get_experiment_overview(experiment_id: str = "") -> dict:
    eid = experiment_id or EXPERIMENT["id"]
    if eid != EXPERIMENT["id"]:
        for exp in ALL_EXPERIMENTS:
            if exp["id"] == eid:
                return {
                    "id": exp["id"], "name": exp["name"],
                    "status": exp["status"], "period": exp["period"],
                    "note": "该实验已结束，仅提供摘要数据。详细指标请选择推荐算法升级实验进行完整演示",
                }
        return {"error": f"未找到实验 {eid}。可用实验见 get_experiment_list"}
    return EXPERIMENT
