"""Simpson 悖论检测：按设备、活跃度下钻 CVR。"""

import numpy as np
from scipy import stats

from .registry import register_tool, _py
from .data import EXPERIMENT, SEGMENT_BREAKDOWN


@register_tool(
    name="check_segment_consistency",
    schema={
        "type": "function",
        "function": {
            "name": "check_segment_consistency",
            "description": "按设备类型、用户活跃度等维度下钻，检查各细分群体的 CVR 变化方向是否与总体一致，防止 Simpson 悖论。",
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
def check_segment_consistency(experiment_id: str = "") -> dict:
    eid = experiment_id or EXPERIMENT["id"]
    if eid != EXPERIMENT["id"]:
        return {"error": f"细分数据仅对推荐算法升级实验可用，当前实验 {eid} 无细分数据"}

    findings = []
    for dim_key, segments in SEGMENT_BREAKDOWN.items():
        dim_name = "设备类型" if dim_key == "by_device" else "用户活跃度"
        for seg in segments:
            lift = seg["lift_pct"]
            p1, n1 = seg["treatment_cvr"], seg["n_treatment"]
            p2, n2 = seg["control_cvr"], seg["n_control"]
            se = np.sqrt(p1*(1-p1)/n1 + p2*(1-p2)/n2)
            z = (p1 - p2) / se if se > 0 else 0
            p_val = 2 * (1 - stats.norm.cdf(abs(z)))

            status = "✅" if lift > 0 else ("⚠️" if p_val > 0.05 else "❌")
            findings.append({
                "dimension": dim_name, "segment": seg["segment"],
                "traffic_pct": seg["traffic_pct"],
                "sample_n": _py(n1 + n2),
                "control_cvr": seg["control_cvr"],
                "treatment_cvr": seg["treatment_cvr"],
                "lift_pct": lift,
                "p_value": _py(round(p_val, 4)),
                "significant": _py(p_val < 0.05),
                "status": status,
                "note": seg.get("note", ""),
            })

    negative_segments = [f for f in findings if f["lift_pct"] < 0]
    has_simpson_risk = _py(len(negative_segments) > 0)

    return {
        "experiment_id": eid,
        "has_simpson_risk": has_simpson_risk,
        "simpson_note": (
            "总体 CVR 提升，但以下细分群体反向："
            + ", ".join(f"{s['segment']}({s['lift_pct']:+.1f}%)" for s in negative_segments)
            if has_simpson_risk
            else "所有细分方向一致，无 Simpson 悖论风险"
        ),
        "findings": findings,
    }
