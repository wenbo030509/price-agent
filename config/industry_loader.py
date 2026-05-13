"""
config/industry_loader.py
行业 Config 加载器 — 按行业名动态加载配置模块，模块级缓存，默认值补齐。
"""
import importlib
from typing import Dict, Optional

# 模块级缓存：同一行业只加载一次
_industry_configs: Dict[str, dict] = {}

# 默认 Config — 当行业 Config 缺失某字段时的 fallback
_DEFAULT_CONFIG: dict = {
    "category": "",
    "embedding_fields": [],
    "filter_fields": {
        "exact": [],
        "range": [],
        "tag_match": [],
    },
    "sort_strategies": {
        "value": "performance_score / price * 10000",
        "price": "-price",
    },
    "use_case_taxonomy": [],
    "performance_tier_map": {"flagship": 100, "mid": 65, "budget": 35},
    "processor_normalize": {},
    "recommend_dimensions": [],
    "compare_dimensions": [],
    "shopping_slots": [],
    "max_slot_questions": 3,
    "prompts": {},
    "enable_vector_recall": False,
    "enable_llm_rerank": False,
    "enable_rag": False,
    "product_display_fields": [],
}


def load_industry_config(industry: str = "mobile") -> dict:
    """
    加载行业 Config。模块级缓存，同一行业首次加载后缓存。

    Args:
        industry: 行业标识，对应 config/industries/<industry>.py

    Returns:
        完整的行业 Config dict，缺失字段用 _DEFAULT_CONFIG 补齐
    """
    if industry in _industry_configs:
        return _industry_configs[industry]

    raw = {}
    try:
        module = importlib.import_module(f"config.industries.{industry}")
        # 模块中定义的 <INDUSTRY>_CONFIG 大写变量
        var_name = f"{industry.upper()}_CONFIG"
        raw = getattr(module, var_name, {})
    except ImportError:
        # 行业模块不存在 → 返回纯默认值
        pass

    # 用默认值补齐缺失字段（浅合并，嵌套 dict 做深度合并）
    config = {}
    for key, default_val in _DEFAULT_CONFIG.items():
        if key in raw:
            val = raw[key]
            # 嵌套 dict 需要深度合并
            if isinstance(default_val, dict) and isinstance(val, dict):
                merged = {**default_val, **val}
                config[key] = merged
            else:
                config[key] = val
        else:
            config[key] = default_val

    # 保留默认值里没有的额外字段
    for key, val in raw.items():
        if key not in config:
            config[key] = val

    _industry_configs[industry] = config
    return config


def get_industry_config(industry: str, key: str, default=None):
    """
    读取 Config 中的单个字段。

    Args:
        industry: 行业标识
        key: 字段名，支持点号分隔的嵌套 key（如 "filter_fields.exact"）
        default: 默认值

    Returns:
        字段值
    """
    config = load_industry_config(industry)

    if "." in key:
        parts = key.split(".")
        current = config
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return default
        return current if current is not None else default

    return config.get(key, default)


def clear_cache(industry: Optional[str] = None):
    """清除缓存（测试用）"""
    global _industry_configs
    if industry:
        _industry_configs.pop(industry, None)
    else:
        _industry_configs.clear()
