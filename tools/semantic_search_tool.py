"""
tools/semantic_search_tool.py
语义推荐工具 — 根据使用场景、预算、品牌、处理器等条件推荐商品。

M2 升级：支持向量召回 + 规则过滤混合检索。
通过 industry_config.enable_vector_recall 开关控制，关闭时与改动前行为完全一致。
"""
import json
import numpy as np
from typing import Dict, Optional, List

from .registry import register_tool
from platforms import PlatformParallelAgent

# 性价比评分权重
TIER_SCORE = {"flagship": 100, "mid": 65, "budget": 35}

# 模块级缓存（懒加载）
_industry_config = None
_embedding_client = None


def _get_agent():
    return PlatformParallelAgent()


def _get_industry_config() -> dict:
    global _industry_config
    if _industry_config is None:
        from config import load_industry_config
        _industry_config = load_industry_config("mobile")
    return _industry_config


def _get_embedding_client():
    global _embedding_client
    if _embedding_client is None:
        from config import Settings
        _embedding_client = Settings().embedding_client
    return _embedding_client


# ── 商品文本构造 ──────────────────────────────────────────────────────

def build_product_text(product: dict, fields: List[str]) -> str:
    """
    将商品的结构化字段拼接为自然语言文本，用于 embedding。

    手机示例输出:
        商品名：iPhone 15 Pro 黑色 256GB
        品牌：Apple
        描述：A17 Pro芯片，钛金属机身，专业摄像
        场景标签：gaming, photography, flagship
        处理器：A17 Pro
    """
    field_labels = {
        "product_name": "商品名",
        "description": "描述",
        "use_case_tags": "场景标签",
        "processor": "处理器",
        "brand": "品牌",
    }
    parts = []
    for field in fields:
        value = product.get(field)
        if value is not None and value != "":
            label = field_labels.get(field, field)
            # use_case_tags 是 JSON 数组字符串，转为可读文本
            if field == "use_case_tags":
                try:
                    tags = json.loads(value) if isinstance(value, str) else value
                    value = "、".join(tags)
                except (json.JSONDecodeError, TypeError):
                    pass
            parts.append(f"{label}：{value}")
    return "\n".join(parts)


# ── 向量召回 ──────────────────────────────────────────────────────────

def _vector_recall(
    query: str,
    products: List[dict],
    embedding_fields: List[str],
    top_k: int = 50,
) -> List[dict]:
    """
    向量召回：query embedding × product embeddings → cosine similarity → top-K。

    embedding 优先从全局缓存（init_product_embeddings 预热）读取，
    缓存未命中时实时计算并回填缓存。
    """
    from platforms.parallel_agent import get_cached_embedding, _product_embedding_cache

    client = _get_embedding_client()
    query_vec = client.embed_text(query)

    scores = []
    for product in products:
        name = product.get("product_name", "")
        p_vec = get_cached_embedding(name)

        if p_vec is None:
            # 缓存未命中 → 实时计算并缓存
            text = build_product_text(product, embedding_fields)
            p_vec = client.embed_text(text)
            if name:
                _product_embedding_cache[name] = p_vec

        similarity = float(np.dot(query_vec, p_vec) / (
            np.linalg.norm(query_vec) * np.linalg.norm(p_vec)
        ))
        scores.append((similarity, product))

    scores.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scores[:top_k]]


# ── 语义推荐工具 ──────────────────────────────────────────────────────

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
    # ── Step 1: 聚合所有平台候选商品 ──
    agent = _get_agent()
    result = agent.query_all_products_parallel()

    all_products = []
    for platform_id, data in result.get("results", {}).items():
        platform_name = data.get("platform_name", platform_id)
        for p in data.get("products", []):
            p["_platform_name"] = platform_name
            all_products.append(p)

    # ── Step 2: 去重（同名保留最低价）──
    best_by_name = {}
    for p in all_products:
        name = p.get("product_name", "")
        price = p.get("platform_price") or p.get("price", 0)
        if name not in best_by_name or price < (best_by_name[name].get("platform_price") or best_by_name[name].get("price", float("inf"))):
            best_by_name[name] = p
    candidates = list(best_by_name.values())

    # ── Step 3: 规则过滤闭包 ──
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

    # ── M2: 向量召回（在规则过滤前扩大候选池）──
    industry_config = _get_industry_config()
    enable_vector = industry_config.get("enable_vector_recall", False)

    if enable_vector:
        embedding_fields = industry_config.get("embedding_fields", [])
        # 向量召回：用 use_case / brand / processor_brand 拼接 query 文本
        query_parts = [use_case, brand, processor_brand, category]
        query_text = " ".join(p for p in query_parts if p).strip() or "手机推荐"

        vector_results = _vector_recall(query_text, candidates, embedding_fields, top_k=50)

        # 向量结果优先（保留语义排序），规则结果补充
        hybrid = []
        seen = set()
        for item in vector_results:
            if _passes(item):
                hybrid.append(item)
                seen.add(item.get("product_name"))

        # 补充：规则命中但向量未命中的商品
        for item in candidates:
            if item.get("product_name") not in seen and _passes(item):
                seen.add(item.get("product_name"))
                hybrid.append(item)

        candidates = hybrid
    else:
        # 纯规则模式（与改动前一致）
        candidates = [item for item in candidates if _passes(item)]

    # ── Step 4: 排序 ──
    candidates.sort(key=lambda x: _value_score(x, sort_by), reverse=True)
    top_items = candidates[:top_n]

    if not top_items:
        return {
            "success": False,
            "total_found": 0,
            "message": "未找到符合条件的商品",
            "suggestions": "您可以放宽条件重试，例如去掉处理器限制或提高预算上限"
        }

    # ── Step 5: 格式化返回 ──
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
        "total_found": len(candidates),
        "recommendations": recommendations,
        "filter_summary": f"品类={category}, 预算={budget_str}, 场景={use_case or '不限'}, 排序={sort_by}"
    }


# ── 排序 ──────────────────────────────────────────────────────────────

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
