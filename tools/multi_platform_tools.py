"""
tools/multi_platform_tools.py  —— 修复版本
修复点（Fix-3）：query_single_platform_product 增加 LLM 属性解析，
                  multi_platform_price_comparison 同步传入 color/memory 参数。
"""
import json
from typing import Dict, Optional

from openai import OpenAI

from .registry import register_tool
from platforms import PlatformParallelAgent, format_comparison_result


_parallel_agent: PlatformParallelAgent = None


def init_parallel_agent():
    global _parallel_agent
    if _parallel_agent is None:
        _parallel_agent = PlatformParallelAgent()
    return _parallel_agent


def get_parallel_agent() -> PlatformParallelAgent:
    return init_parallel_agent()


def _parse_attrs_from_query(raw_query: str, llm_client: OpenAI, model: str) -> Dict:
    prompt = f"""从用户输入中提取商品属性，只输出 JSON，不要其他任何文字。

用户输入：{raw_query}

输出格式（所有字段都必须有，未提及的填空字符串""）：
{{
  "product_name": "商品核心名称（去掉颜色内存等修饰词）",
  "color": "颜色（如黑色、白色、蓝色，未提及填""）",
  "memory": "内存或容量（如128GB、256GB、512GB，未提及填""）",
  "category": "品类（如手机、平板、耳机，不确定填""）"
}}"""

    try:
        resp = llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=150,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.strip("`").lstrip("json").strip()
        attrs = json.loads(raw)
        return {
            "product_name": attrs.get("product_name", raw_query) or raw_query,
            "color": attrs.get("color", ""),
            "memory": attrs.get("memory", ""),
            "category": attrs.get("category", ""),
        }
    except Exception:
        return {"product_name": raw_query, "color": "", "memory": "", "category": ""}


def _get_llm_client():
    from config import Settings
    s = Settings()
    return s.client, s.model


@register_tool(
    name="multi_platform_price_comparison",
    schema={
        "type": "function",
        "function": {
            "name": "multi_platform_price_comparison",
            "description": (
                "在多个电商平台（京东、淘宝、拼多多、苏宁）并行查询商品价格。"
                "支持附加颜色、内存等属性精确匹配，找出最低价平台。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "商品名称，如 'iPhone 15'、'小米14'。可包含颜色/内存，工具会自动解析。",
                    },
                    "color": {
                        "type": "string",
                        "description": "颜色筛选，如 '黑色'、'蓝色'。可不传。",
                    },
                    "memory": {
                        "type": "string",
                        "description": "内存/容量筛选，如 '256GB'、'512GB'。可不传。",
                    },
                },
                "required": ["product_name"],
            },
        },
    },
)
def multi_platform_price_comparison(
    product_name: str,
    color: Optional[str] = None,
    memory: Optional[str] = None,
) -> Dict:
    attr_keywords = ["黑", "白", "蓝", "紫", "红", "粉", "金", "绿",
                     "128", "256", "512", "1T", "1t", "GB", "gb"]
    needs_parse = (not color and not memory and
                   any(kw in product_name for kw in attr_keywords))

    if needs_parse:
        client, model = _get_llm_client()
        attrs = _parse_attrs_from_query(product_name, client, model)
        product_name = attrs["product_name"]
        color = attrs["color"] or color
        memory = attrs["memory"] or memory

    agent = get_parallel_agent()
    comparison = agent.compare_product_price(
        product_name,
        color=color or None,
        memory=memory or None,
    )
    formatted_text = format_comparison_result(comparison)

    return {"raw_data": comparison, "formatted_text": formatted_text}


@register_tool(
    name="get_all_platform_products",
    schema={
        "type": "function",
        "function": {
            "name": "get_all_platform_products",
            "description": "获取所有平台的所有商品列表",
            "parameters": {"type": "object", "properties": {}},
        },
    },
)
def get_all_platform_products() -> Dict:
    agent = get_parallel_agent()
    result = agent.query_all_products_parallel()

    lines = ["📦 各平台商品列表", "=" * 70]
    for platform_id, data in result["results"].items():
        platform_name = data["platform_name"]
        products = data["products"]
        lines.append(f"\n🛒 {platform_name} ({len(products)}个商品):")
        for p in products:
            lines.append(f"   • {p['product_name']}: ¥{p['platform_price']}")
    if result["errors"]:
        lines.append(f"\n⚠️  查询出错的平台: {', '.join(result['errors'].keys())}")

    return {"raw_data": result, "formatted_text": "\n".join(lines)}


@register_tool(
    name="query_single_platform_product",
    schema={
        "type": "function",
        "function": {
            "name": "query_single_platform_product",
            "description": "查询指定平台的商品信息，支持颜色、内存属性精确筛选",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform_id": {
                        "type": "string",
                        "description": "平台ID: jd(京东), taobao(淘宝), pdd(拼多多), suning(苏宁)",
                        "enum": ["jd", "taobao", "pdd", "suning"],
                    },
                    "product_name": {
                        "type": "string",
                        "description": "商品名称（可包含颜色/内存，工具自动解析）",
                    },
                    "color": {
                        "type": "string",
                        "description": "颜色筛选，如 '黑色'（可不传）",
                    },
                    "memory": {
                        "type": "string",
                        "description": "内存/容量，如 '256GB'（可不传）",
                    },
                },
                "required": ["platform_id", "product_name"],
            },
        },
    },
)
def query_single_platform_product(
    platform_id: str,
    product_name: str,
    color: Optional[str] = None,
    memory: Optional[str] = None,
) -> Dict:
    from platforms import PlatformDatabase, get_platform_config

    config = get_platform_config(platform_id)
    db = PlatformDatabase(platform_id)

    result = db.query_product_by_attrs(
        product_name=product_name,
        color=color or None,
        memory=memory or None,
    )
    db.close()

    if result:
        match_info = []
        if color and result.get("color"):
            match_info.append(f"颜色={result['color']}")
        if memory and result.get("memory"):
            match_info.append(f"内存={result['memory']}")

        return {
            "success": True,
            "platform": config["name"],
            "product": result,
            "matched_attrs": match_info,
        }
    else:
        return {
            "success": False,
            "platform": config["name"],
            "message": f"在{config['name']}未找到「{product_name}」",
        }


def cleanup_parallel_agent():
    global _parallel_agent
    if _parallel_agent is not None:
        _parallel_agent.close()
        _parallel_agent = None