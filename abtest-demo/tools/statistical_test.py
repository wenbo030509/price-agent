"""Welch's t-test 单指标统计检验。"""

import numpy as np
from scipy import stats

from .registry import register_tool, _py
from .data import METRICS


@register_tool(
    name="run_statistical_test",
    schema={
        "type": "function",
        "function": {
            "name": "run_statistical_test",
            "description": "对单个指标执行 Welch's t 检验。推荐用 metric_key 参数直接指定指标名（如 'cvr'）。返回 p 值、95% CI、Cohen's d 效应量。对每个指标分别调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_key": {"type": "string", "description": "指标 key: cvr, gmv_per_user, ctr, session_duration_s, bounce_rate, api_latency_ms, complaint_rate"},
                    "control_mean": {"type": "number", "description": "对照组均值（metric_key 为空时必填）"},
                    "control_std": {"type": "number"},
                    "control_n": {"type": "integer"},
                    "treatment_mean": {"type": "number"},
                    "treatment_std": {"type": "number"},
                    "treatment_n": {"type": "integer"},
                    "higher_is_better": {"type": "boolean"},
                    "metric_name": {"type": "string"},
                    "metric_type": {"type": "string"},
                },
                "required": [],
            },
        },
    },
)
def run_statistical_test(
    metric_key: str = "",
    control_mean: float = 0, control_std: float = 0, control_n: int = 0,
    treatment_mean: float = 0, treatment_std: float = 0, treatment_n: int = 0,
    higher_is_better: bool = True,
    metric_name: str = "", metric_type: str = "",
) -> dict:
    if metric_key and metric_key in METRICS:
        m = METRICS[metric_key]
        control_mean = m["control"]["mean"]
        control_std = m["control"]["std"]
        control_n = m["control"]["n"]
        treatment_mean = m["treatment"]["mean"]
        treatment_std = m["treatment"]["std"]
        treatment_n = m["treatment"]["n"]
        higher_is_better = m["higher_is_better"]
        metric_name = metric_name or m["name"]
        metric_type = metric_type or m["type"]

    if control_n == 0 or treatment_n == 0:
        return {"error": "样本量不能为 0"}

    t_stat, p_value = stats.ttest_ind_from_stats(
        mean1=treatment_mean, std1=treatment_std, nobs1=treatment_n,
        mean2=control_mean, std2=control_std, nobs2=control_n,
        equal_var=False,
    )

    diff = treatment_mean - control_mean
    pooled_se = np.sqrt(treatment_std**2 / treatment_n + control_std**2 / control_n)
    ci_lower = diff - 1.96 * pooled_se
    ci_upper = diff + 1.96 * pooled_se
    relative_lift = (diff / control_mean) * 100

    pooled_sd = np.sqrt((treatment_std**2 + control_std**2) / 2)
    cohens_d = diff / pooled_sd if pooled_sd > 0 else 0

    is_significant = p_value < 0.05
    positive = diff > 0 if higher_is_better else diff < 0

    if abs(cohens_d) < 0.2:
        effect_label = "微小"
    elif abs(cohens_d) < 0.5:
        effect_label = "小-中等"
    elif abs(cohens_d) < 0.8:
        effect_label = "中等"
    else:
        effect_label = "大"

    verdict = (
        "✅ 显著改善" if (is_significant and positive)
        else ("❌ 显著恶化" if (is_significant and not positive) else "➖ 无显著差异")
    )

    return {
        "metric": metric_name, "metric_key": metric_key, "metric_type": metric_type,
        "control": {"mean": control_mean, "std": control_std, "n": control_n},
        "treatment": {"mean": treatment_mean, "std": treatment_std, "n": treatment_n},
        "absolute_diff": round(_py(diff), 6),
        "relative_lift_pct": round(_py(relative_lift), 2),
        "p_value": _py(float(f"{p_value:.6f}")),
        "is_significant": _py(is_significant),
        "ci_95": [round(_py(ci_lower), 6), round(_py(ci_upper), 6)],
        "cohens_d": round(_py(cohens_d), 2),
        "effect_size": effect_label,
        "verdict": verdict,
    }
