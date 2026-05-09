"""
多平台比价工具
集成多agent并行查询功能
"""
from typing import Dict
from .registry import register_tool
from platforms import PlatformParallelAgent, format_comparison_result


# 全局并行Agent实例
_parallel_agent: PlatformParallelAgent = None


def init_parallel_agent():
    """初始化并行Agent"""
    global _parallel_agent
    if _parallel_agent is None:
        _parallel_agent = PlatformParallelAgent()
    return _parallel_agent


def get_parallel_agent() -> PlatformParallelAgent:
    """获取并行Agent实例"""
    return init_parallel_agent()


@register_tool(
    name="multi_platform_price_comparison",
    schema={
        "type": "function",
        "function": {
            "name": "multi_platform_price_comparison",
            "description": "在多个电商平台（京东、淘宝、拼多多、苏宁）并行查询商品价格，找出最低价平台",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "要查询的商品名称，如'iPhone 15'、'小米14'等"
                    }
                },
                "required": ["product_name"]
            }
        }
    }
)
def multi_platform_price_comparison(product_name: str) -> Dict:
    """
    多平台比价工具
    :param product_name: 商品名称
    :return: 比价结果字典
    """
    agent = get_parallel_agent()
    comparison = agent.compare_product_price(product_name)
    formatted_text = format_comparison_result(comparison)
    
    return {
        "raw_data": comparison,
        "formatted_text": formatted_text
    }


@register_tool(
    name="get_all_platform_products",
    schema={
        "type": "function",
        "function": {
            "name": "get_all_platform_products",
            "description": "获取所有平台的所有商品列表",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
)
def get_all_platform_products() -> Dict:
    """
    获取所有平台所有商品
    :return: 各平台商品列表
    """
    agent = get_parallel_agent()
    result = agent.query_all_products_parallel()
    
    # 格式化输出
    lines = ["📦 各平台商品列表"]
    lines.append("=" * 70)
    
    for platform_id, data in result["results"].items():
        platform_name = data["platform_name"]
        products = data["products"]
        lines.append(f"\n🛒 {platform_name} ({len(products)}个商品):")
        for p in products:
            lines.append(f"   • {p['product_name']}: ¥{p['platform_price']}")
    
    if result["errors"]:
        lines.append(f"\n⚠️  查询出错的平台: {', '.join(result['errors'].keys())}")
    
    return {
        "raw_data": result,
        "formatted_text": "\n".join(lines)
    }


@register_tool(
    name="query_single_platform_product",
    schema={
        "type": "function",
        "function": {
            "name": "query_single_platform_product",
            "description": "查询指定平台的商品信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform_id": {
                        "type": "string",
                        "description": "平台ID: jd(京东), taobao(淘宝), pdd(拼多多), suning(苏宁)",
                        "enum": ["jd", "taobao", "pdd", "suning"]
                    },
                    "product_name": {
                        "type": "string",
                        "description": "要查询的商品名称"
                    }
                },
                "required": ["platform_id", "product_name"]
            }
        }
    }
)
def query_single_platform_product(platform_id: str, product_name: str) -> Dict:
    """
    查询单个平台的商品
    :param platform_id: 平台ID
    :param product_name: 商品名称
    :return: 查询结果
    """
    from platforms import PlatformDatabase, get_platform_config
    
    config = get_platform_config(platform_id)
    db = PlatformDatabase(platform_id)
    
    result = db.query_product(product_name)
    db.close()
    
    if result:
        return {
            "success": True,
            "platform": config["name"],
            "product": result
        }
    else:
        return {
            "success": False,
            "platform": config["name"],
            "message": f"在{config['name']}未找到「{product_name}」"
        }


def cleanup_parallel_agent():
    """清理并行Agent资源"""
    global _parallel_agent
    if _parallel_agent is not None:
        _parallel_agent.close()
        _parallel_agent = None
