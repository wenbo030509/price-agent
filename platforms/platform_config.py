"""
多平台配置
定义各个电商平台的配置信息
"""

PLATFORMS = {
    "jd": {
        "name": "京东",
        "db_path": "platform_jd.db",
        "color": "#E4393C",
        "icon": "🛒"
    },
    "taobao": {
        "name": "淘宝",
        "db_path": "platform_taobao.db",
        "color": "#FF6600",
        "icon": "🛍️"
    },
    "pdd": {
        "name": "拼多多",
        "db_path": "platform_pdd.db",
        "color": "#E62E2D",
        "icon": "🎁"
    },
    "suning": {
        "name": "苏宁",
        "db_path": "platform_suning.db",
        "color": "#FF5000",
        "icon": "📺"
    }
}


def get_platform_config(platform_id: str) -> dict:
    """获取指定平台的配置"""
    return PLATFORMS.get(platform_id, {})


def get_all_platforms() -> dict:
    """获取所有平台配置"""
    return PLATFORMS


def get_platform_ids() -> list:
    """获取所有平台ID列表"""
    return list(PLATFORMS.keys())
