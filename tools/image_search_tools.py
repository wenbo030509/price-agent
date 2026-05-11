"""
图片搜索工具 — 多模态 LLM 提取商品属性 → 文本搜索链路
"""
import json
from typing import Dict, Optional
from openai import OpenAI

from .registry import register_tool
from platforms import PlatformParallelAgent, format_comparison_result


# ── 图片属性提取 ────────────────────────────────────────────────────────────


def _extract_attrs_from_image(
    image_url: str,
    client: OpenAI,
    model: str,
) -> Dict:
    """用多模态 LLM 从图片中提取商品结构化属性"""
    prompt = """识别这张图片中的商品，只输出JSON，不要其他任何文字。

输出格式（所有字段都必须有）：
{
  "product_name": "商品核心名称（如 iPhone 15、小米14、AirPods Pro 2），如果无法识别填''",
  "color": "颜色（如 黑色、白色、蓝色），如果无法识别填''",
  "category": "品类（如 手机、平板、耳机、服饰、鞋包），如果无法识别填''",
  "brand": "品牌（如 Apple、小米、华为），如果无法识别填''",
  "confidence": "high|medium|low（识别置信度）"
}

规则：
- 只输出商品信息，不要描述图片背景、场景等无关内容
- 如果图片中有多个商品，只识别最主要/最突出的那个
- 如果确实无法识别任何商品信息，所有字段填空字符串，confidence 填 low"""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }],
            temperature=0,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.strip("`").lstrip("json").strip()
        attrs = json.loads(raw)
        return {
            "product_name": attrs.get("product_name", ""),
            "color": attrs.get("color", ""),
            "category": attrs.get("category", ""),
            "brand": attrs.get("brand", ""),
            "confidence": attrs.get("confidence", "low"),
        }
    except Exception as e:
        return {
            "product_name": "",
            "color": "",
            "category": "",
            "brand": "",
            "confidence": "low",
            "error": str(e),
        }


def _get_vision_client():
    """获取多模态识别的 client 和 model"""
    from config import Settings
    s = Settings()
    return s.client, getattr(s, "model_vision", s.model)


# ── 图片搜索工具 ────────────────────────────────────────────────────────────


@register_tool(
    name="search_product_by_image",
    schema={
        "type": "function",
        "function": {
            "name": "search_product_by_image",
            "description": (
                "根据用户上传的商品图片识别商品，并在京东、淘宝、拼多多、苏宁4个平台"
                "搜索同款/相似商品的价格。适用于用户拍照搜同款的场景。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image_url": {
                        "type": "string",
                        "description": "商品图片的URL地址",
                    },
                    "color": {
                        "type": "string",
                        "description": "用户额外指定的颜色偏好（可选，不填则用图片识别结果）",
                    },
                    "memory": {
                        "type": "string",
                        "description": "用户额外指定的内存/容量偏好（可选）",
                    },
                },
                "required": ["image_url"],
            },
        },
    },
)
def search_product_by_image(
    image_url: str,
    color: Optional[str] = None,
    memory: Optional[str] = None,
) -> Dict:
    """
    图片搜索商品工具。
    流程：多模态 LLM 提取属性 → multi_platform_price_comparison 文本搜索。
    """
    # Step 1: 图片识别
    client, model = _get_vision_client()
    attrs = _extract_attrs_from_image(image_url, client, model)

    product_name = attrs.get("product_name", "")
    confidence = attrs.get("confidence", "low")

    # 如果识别失败（无法提取商品名）
    if not product_name:
        return {
            "success": False,
            "image_attrs": attrs,
            "message": (
                "未能从图片中识别出明确的商品信息。"
                "请确保图片清晰、商品主体突出，或直接输入商品名称搜索。"
            ),
        }

    # Step 2: 用识别属性 + 用户指定的偏好进行文本搜索
    search_name = product_name
    search_color = color or attrs.get("color") or None
    search_memory = memory or None

    # 如果 confidence 低但识别出了 product_name，仍然搜索但标注低置信度
    agent = _get_parallel_agent()
    comparison = agent.compare_product_price(
        search_name,
        color=search_color,
        memory=search_memory,
    )
    formatted_text = format_comparison_result(comparison)

    result = {
        "success": True,
        "image_attrs": attrs,
        "search_query": {
            "product_name": search_name,
            "color": search_color,
            "memory": search_memory,
        },
        "comparison": comparison,
        "formatted_text": formatted_text,
    }

    # 低置信度时追加提示
    if confidence == "low" and comparison.get("found"):
        result["warning"] = "图片识别置信度较低，结果可能不完全匹配，建议输入商品名称精确搜索。"

    return result


def _get_parallel_agent() -> PlatformParallelAgent:
    """获取并行查询 agent（复用全局单例或新建）"""
    try:
        from tools.multi_platform_tools import get_parallel_agent
        return get_parallel_agent()
    except Exception:
        agent = PlatformParallelAgent()
        return agent
