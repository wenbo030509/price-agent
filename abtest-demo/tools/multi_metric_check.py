"""Bonferroni 多重比较校正 + 多指标汇总。"""

import json

from .registry import register_tool, _py


@register_tool(
    name="run_multi_metric_check",
    schema={
        "type": "function",
        "function": {
            "name": "run_multi_metric_check",
            "description": "综合所有指标的检验结果，自动应用 Bonferroni 多重比较校正。汇总主指标和护栏指标状态。所有单指标检验完成后调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_results_json": {"type": "string", "description": "run_statistical_test 返回结果组成的 JSON 数组字符串"},
                },
                "required": ["test_results_json"],
            },
        },
    },
)
def run_multi_metric_check(test_results_json: str) -> dict:
    try:
        results = json.loads(test_results_json)
    except json.JSONDecodeError:
        return {"error": "输入格式错误，需要 JSON 数组字符串"}
    if not isinstance(results, list):
        return {"error": "输入必须是数组"}

    n_tests = len(results)
    bonferroni_alpha = _py(0.05 / n_tests if n_tests > 0 else 0.05)

    primary_pass = None
    guardrail_violations = []

    for r in results:
        mt = r.get("metric_type", "")
        p = r.get("p_value", 1.0)
        sig = r.get("is_significant", False)
        lift = r.get("relative_lift_pct", 0)
        name = r.get("metric", "?")

        if mt == "primary":
            primary_pass = sig and lift > 0
        elif mt == "guardrail":
            if sig and lift < 0:
                guardrail_violations.append({
                    "metric": name, "p_value": p, "lift_pct": lift,
                })

    if primary_pass is None:
        overall = "无法判断（缺少主指标）"
    elif primary_pass and len(guardrail_violations) == 0:
        overall = "✅ 建议上线：主指标显著提升，护栏全部通过"
    elif primary_pass and len(guardrail_violations) > 0:
        overall = "⚠️ 条件上线：主指标提升但护栏触发，需针对性优化后上线"
    elif not primary_pass:
        overall = "❌ 建议下线/回滚：主指标未显著提升"
    else:
        overall = "➖ 建议延长实验"

    return {
        "total_metrics": n_tests,
        "bonferroni_alpha": round(bonferroni_alpha, 6),
        "bonferroni_note": f"多重比较校正：α={0.05}/{n_tests}={bonferroni_alpha:.6f}",
        "primary_pass": primary_pass,
        "guardrail_violations": guardrail_violations,
        "overall_verdict": overall,
    }
