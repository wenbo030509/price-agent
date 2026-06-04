"""综合决策：上线 / 条件上线 / 下线 / 延长实验。"""

import json

from .registry import register_tool
from .data import EXPERIMENT


@register_tool(
    name="make_strategy_decision",
    schema={
        "type": "function",
        "function": {
            "name": "make_strategy_decision",
            "description": "综合多指标检验和细分分析结果，给出最终决策建议（全量上线/条件上线/下线/延长实验）。所有分析完成后最后调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "multi_metric_result_json": {"type": "string", "description": "run_multi_metric_check 返回的 JSON 字符串"},
                    "segment_result_json": {"type": "string", "description": "check_segment_consistency 返回的 JSON 字符串"},
                },
                "required": ["multi_metric_result_json"],
            },
        },
    },
)
def make_strategy_decision(
    multi_metric_result_json: str = "",
    segment_result_json: str = "",
) -> dict:
    try:
        metric_check = json.loads(multi_metric_result_json) if multi_metric_result_json else {}
        segment_check = json.loads(segment_result_json) if segment_result_json else {}
    except json.JSONDecodeError:
        return {"error": "输入 JSON 格式错误"}

    primary_pass = metric_check.get("primary_pass", None)
    violations = metric_check.get("guardrail_violations", [])
    simpson_risk = segment_check.get("has_simpson_risk", False)

    if primary_pass and not violations and not simpson_risk:
        decision = "✅ 建议全量上线"
        reasons = ["主指标显著提升", "所有护栏指标安全", "细分维度无反向趋势"]
        next_steps = ["执行全量上线", "上线后持续监控 7 天"]
    elif primary_pass and (violations or simpson_risk):
        decision = "⚠️ 条件上线（需先解决以下问题）"
        reasons = ["主指标显著提升"]
        remedies = []
        if violations:
            for v in violations:
                reasons.append(f"护栏指标「{v['metric']}」触发：{v['lift_pct']:+.1f}% (p={v['p_value']})")
                if "延迟" in v["metric"]:
                    remedies.append("工程优化：模型量化 + 异步预计算，目标将延迟降至 200ms 以下")
        if simpson_risk:
            reasons.append("存在细分群体反向趋势，需关注")
            remedies.append("对反向细分群体做小流量灰度验证")
        next_steps = remedies + ["优化完成后再执行全量上线"]
    elif not primary_pass:
        decision = "❌ 建议下线/回滚"
        reasons = ["主指标未显著提升"]
        next_steps = ["分析失败原因", "修复后重新设计实验"]
    else:
        decision = "➖ 建议延长实验"
        reasons = ["当前数据不足以得出结论"]
        next_steps = ["延长实验周期至 21 天", "或扩大样本量至 60000/组"]

    return {
        "decision": decision,
        "reasons": reasons,
        "next_steps": next_steps,
        "experiment_id": EXPERIMENT["id"],
        "metrics_summary": {
            "primary_pass": primary_pass,
            "guardrail_violations_count": len(violations),
            "simpson_risk": simpson_risk,
        },
    }
