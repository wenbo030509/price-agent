"""分日趋势数据（CVR + 延迟）。"""

from .registry import register_tool
from .data import EXPERIMENT, DAILY_SERIES


@register_tool(
    name="get_daily_trend",
    schema={
        "type": "function",
        "function": {
            "name": "get_daily_trend",
            "description": "获取实验期间的每日趋势数据（CVR 和延迟），用于判断效果稳定性和学习效应。",
            "parameters": {
                "type": "object",
                "properties": {
                    "experiment_id": {"type": "string", "description": "实验 ID"},
                },
                "required": [],
            },
        },
    },
)
def get_daily_trend(experiment_id: str = "") -> dict:
    eid = experiment_id or EXPERIMENT["id"]
    if eid != EXPERIMENT["id"]:
        return {"error": f"分日趋势仅对推荐算法升级实验可用，当前实验 {eid} 无趋势数据"}

    tcvr = DAILY_SERIES["treatment_cvr"]
    tlat = DAILY_SERIES["treatment_latency"]
    cvr_improving = tcvr[-1] > tcvr[0]

    return {
        "experiment_id": eid,
        "dates": DAILY_SERIES["dates"],
        "control_cvr": DAILY_SERIES["control_cvr"],
        "treatment_cvr": tcvr,
        "control_latency": DAILY_SERIES["control_latency"],
        "treatment_latency": tlat,
        "observations": {
            "cvr_stable": f"实验组 CVR 从第1天{tcvr[0]:.4f}升至第14天{tcvr[-1]:.4f}，趋势稳定上升",
            "cvr_improving": cvr_improving,
            "latency_note": f"实验组延迟第1周平均{sum(tlat[:7])/7:.0f}ms，第2周降至{sum(tlat[7:])/7:.0f}ms（工程优化后有所改善，但仍远高于对照组的145ms）",
        },
    }
