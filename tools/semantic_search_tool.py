"""
tools/semantic_search_tool.py
语义推荐工具 — 根据使用场景、预算、品牌、处理器等条件推荐商品。
"""
import json
from typing import Dict, Optional

from .registry import register_tool
from platforms import PlatformParallelAgent

# 性价比评分权重（与 query 层 TIER_RANK 不同，这里用于价值计算）
TIER_SCORE = {"flagship": 100, "mid": 65, "budget": 35}


def _get_agent():
    return PlatformParallelAgent()


def _value_score(item: Dict, sort_by: str) -> float:
    tier = TIER_SCORE.get(item.get("performance_tier", "mid"), 50)
    price = item.get("price", 9999)
    if sort_by == "value":
        return tier / price * 10000
    elif sort_by == "price":
        return -price
    elif sort_by == "performance":
        return tier
    return tier / price * 10000


@register_tool(
    name="semantic_product_search",
    schema={
        "type": "function",
        "function": {
            "name": "semantic_product_search",
            "description": "根据使用场景、预算、品牌、处理器等条件推荐商品。适用于：'推荐游戏手机'、'5000以内性价比最高的手机'、'骁龙处理器手机有哪些'、'拍照好的手机'等推荐型需求。与 multi_platform_price_comparison 的区别：本工具做推荐筛选，后者做精确比价。",
            "parameters": {
                "type": "object",
                "properties": {
                    "use_case": {
                        "type": "string",
                        "description": "使用场景标签，可选值：gaming(游戏) photography(拍照) battery(续航) business(商务) student(学生) budget(入门) flagship(旗舰)。多个用逗号分隔，如 'gaming,photography'",
                        "default": ""
                    },
                    "brand": {"type": "string", "description": "品牌偏好，如 'Apple'、'小米'，为空则不限", "default": ""},
                    "processor_brand": {"type": "string", "description": "处理器厂商：sd(骁龙) mt(天玑) apple(A/M系列) kirin(麒麟)，为空则不限", "default": ""},
                    "performance_tier": {"type": "string", "description": "性能层级：flagship/mid/budget，为空则不限", "default": ""},
                    "budget_max": {"type": "number", "description": "最高预算（元），不传则不限"},
                    "budget_min": {"type": "number", "description": "最低预算（元），不传则不限"},
                    "category": {"type": "string", "description": "品类，默认手机", "default": "手机"},
                    "sort_by": {"type": "string", "description": "排序方式：value=性价比优先，price=最低价优先，performance=性能优先", "default": "value"},
                    "top_n": {"type": "integer", "description": "返回推荐数量，默认5", "default": 5}
                },
                "required": []
            }
        }
    },
)
def semantic_product_search(
    use_case: str = "",
    brand: str = "",
    processor_brand: str = "",
    performance_tier: str = "",
    budget_max: Optional[float] = None,
    budget_min: Optional[float] = None,
    category: str = "手机",
    sort_by: str = "value",
    top_n: int = 5,
) -> Dict:
    # Step 1: 聚合所有平台候选商品
    agent = _get_agent()
    result = agent.query_all_products_parallel()

    all_products = []
    for platform_id, data in result.get("results", {}).items():
        platform_name = data.get("platform_name", platform_id)
        for p in data.get("products", []):
            p["_platform_name"] = platform_name
            all_products.append(p)

    # Step 2: 去重（同名保留最低价）
    best_by_name = {}
    for p in all_products:
        name = p.get("product_name", "")
        price = p.get("platform_price") or p.get("price", 0)
        if name not in best_by_name or price < (best_by_name[name].get("platform_price") or best_by_name[name].get("price", float("inf"))):
            best_by_name[name] = p
    candidates = list(best_by_name.values())

    # Step 3: 硬过滤
    use_case_tags = [t.strip().lower() for t in use_case.split(",") if t.strip()]

    def _passes(item: Dict) -> bool:
        if category and item.get("category", "") != category:
            return False
        if budget_max is not None and item.get("price", 0) > budget_max:
            return False
        if budget_min is not None and item.get("price", 0) < budget_min:
            return False
        if brand and item.get("brand", "") != brand:
            return False
        if processor_brand and item.get("processor_brand", "") != processor_brand:
            return False
        if performance_tier and item.get("performance_tier", "") != performance_tier:
            return False
        if use_case_tags:
            item_tags = (item.get("use_case_tags") or "[]").lower()
            for tag in use_case_tags:
                if tag not in item_tags:
                    return False
        return True

    filtered = [item for item in candidates if _passes(item)]

    # Step 4: 排序
    filtered.sort(key=lambda x: _value_score(x, sort_by), reverse=True)
    top_items = filtered[:top_n]

    if not top_items:
        return {
            "success": False,
            "total_found": 0,
            "message": "未找到符合条件的商品",
            "suggestions": "您可以放宽条件重试，例如去掉处理器限制或提高预算上限"
        }

    # Step 5: 格式化返回
    recommendations = []
    for i, item in enumerate(top_items):
        recommendations.append({
            "rank": i + 1,
            "product_name": item["product_name"],
            "brand": item.get("brand", ""),
            "price": item["price"],
            "platform": item["_platform_name"],
            "processor": item.get("processor", ""),
            "performance_tier": item.get("performance_tier", ""),
            "use_case_tags": item.get("use_case_tags", "[]"),
            "description": item.get("description", ""),
            "value_score": round(_value_score(item, sort_by), 2),
        })

    budget_str = f"{budget_min or '不限'}-{budget_max or '不限'}"
    return {
        "success": True,
        "total_found": len(filtered),
        "recommendations": recommendations,
        "filter_summary": f"品类={category}, 预算={budget_str}, 场景={use_case or '不限'}, 排序={sort_by}"
    }
