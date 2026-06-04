"""获取指定实验的所有指标原始数据（均值、标准差、样本量）。"""

from .registry import register_tool
from .data import EXPERIMENT, ALL_EXPERIMENTS, METRICS


@register_tool(
    name="get_experiment_detail",
    schema={
        "type": "function",
        "function": {
            "name": "get_experiment_detail",
            "description": "获取指定实验的所有指标原始数据（对照组和实验组的均值、标准差、样本量）。为后续逐指标统计检验提供输入。",
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
def get_experiment_detail(experiment_id: str = "") -> dict:
    eid = experiment_id or EXPERIMENT["id"]
    if eid != EXPERIMENT["id"]:
        for exp in ALL_EXPERIMENTS:
            if exp["id"] == eid:
                return {
                    "experiment_id": eid,
                    "note": "该实验仅提供摘要数据。完整7指标详情请使用推荐算法升级实验",
                    "metrics_available": False,
                }
        return {"error": f"未找到实验 {eid}"}

    metrics_raw = {}
    for key, m in METRICS.items():
        metrics_raw[key] = {
            "name": m["name"], "type": m["type"],
            "higher_is_better": m["higher_is_better"],
            "control": m["control"], "treatment": m["treatment"],
        }

    return {
        "experiment_id": eid, "experiment_name": EXPERIMENT["name"],
        "total_metrics": len(metrics_raw), "metrics": metrics_raw,
        "instruction": "请对每个指标调用 run_statistical_test(metric_key=...) 进行统计检验",
    }
