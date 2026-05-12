"""
platforms/platform_database.py  —— IT3C 扩展版本（Phase 1-A）
Schema 从 9 列扩展到 17 列，新增 brand/processor/processor_brand/performance_tier/
screen_size/battery/use_case_tags/description。
"""

import re
import sqlite3
from typing import Dict, List, Optional, Tuple

from .platform_config import get_platform_config, get_platform_ids


# ── 各平台 IT3C Mock 数据（17 字段） ─────────────────────────────────────────
_PLATFORM_MOCK_DATA = {
    "jd": [
        ("iPhone 15 黑色 128GB", 5999, 100, "手机", 5999, 0, 1, "黑色", "128GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","gaming","flagship"]', "A16芯片，双摄系统，全天续航"),
        ("iPhone 15 白色 128GB", 5999, 80, "手机", 5999, 0, 1, "白色", "128GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","flagship"]', "A16芯片，双摄系统，全天续航"),
        ("iPhone 15 黑色 256GB", 6999, 50, "手机", 6999, 0, 1, "黑色", "256GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","gaming","flagship"]', "A16芯片，双摄系统，全天续航"),
        ("iPhone 15 白色 256GB", 6999, 60, "手机", 6999, 0, 1, "白色", "256GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","flagship"]', "A16芯片，双摄系统，全天续航"),
        ("iPhone 15 Pro 黑色 256GB", 8999, 40, "手机", 8999, 0, 1, "黑色", "256GB",
         "Apple", "A17 Pro", "apple", "flagship", 6.1, 3274,
         '["gaming","photography","flagship","business"]', "A17 Pro芯片，钛金属机身，专业摄像"),
        ("小米14 黑色 256GB", 3999, 150, "手机", 3999, 0, 1, "黑色", "256GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.36, 4610,
         '["gaming","photography","flagship"]', "骁龙8Gen3，徕卡影像，大电池"),
        ("小米14 白色 256GB", 4099, 120, "手机", 4099, 0, 1, "白色", "256GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.36, 4610,
         '["gaming","photography","flagship"]', "骁龙8Gen3，徕卡影像，大电池"),
        ("小米14 Pro 黑色 512GB", 5299, 80, "手机", 5299, 0, 1, "黑色", "512GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.73, 4880,
         '["gaming","photography","flagship","business"]', "骁龙8Gen3，超大底主摄，专业旗舰"),
        ("红米Note13 蓝色 128GB", 1299, 200, "手机", 1299, 0, 1, "蓝色", "128GB",
         "红米", "天玑6080", "mt", "budget", 6.67, 5000,
         '["budget","student"]', "入门首选，大屏长续航"),
        ("小米平板6 黑色 128GB", 2199, 100, "平板", 2199, 0, 1, "黑色", "128GB",
         "小米", "骁龙870", "sd", "mid", 11.0, 8840,
         '["student","business"]', "高刷大屏，学习办公利器"),
        ("AirPods Pro 2", 1799, 200, "耳机", 1799, 0, 1, "白色", "",
         "Apple", "", "", "flagship", None, None,
         '["flagship","business"]', "主动降噪，空间音频"),
        ("iPad Pro 11寸 256GB", 7999, 30, "平板", 7999, 0, 1, "深空灰", "256GB",
         "Apple", "M2", "apple", "flagship", 11.0, None,
         '["business","flagship"]', "M2芯片，Liquid Retina显示屏"),
    ],
    "taobao": [
        ("iPhone 15 黑色 128GB", 5899, 90, "手机", 5899, 10, 1, "黑色", "128GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","gaming","flagship"]', "A16芯片，双摄系统"),
        ("iPhone 15 蓝色 128GB", 5950, 70, "手机", 5950, 10, 1, "蓝色", "128GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","flagship"]', "A16芯片，双摄系统"),
        ("iPhone 15 黑色 256GB", 6850, 40, "手机", 6850, 10, 1, "黑色", "256GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","gaming","flagship"]', "A16芯片，双摄系统"),
        ("iPhone 15 Pro 黑色 256GB", 8799, 30, "手机", 8799, 10, 1, "黑色", "256GB",
         "Apple", "A17 Pro", "apple", "flagship", 6.1, 3274,
         '["gaming","photography","flagship","business"]', "A17 Pro芯片，钛金属机身"),
        ("小米14 紫色 256GB", 3999, 100, "手机", 3999, 5, 1, "紫色", "256GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.36, 4610,
         '["gaming","photography","flagship"]', "骁龙8Gen3，徕卡影像"),
        ("小米14 黑色 128GB", 3799, 80, "手机", 3799, 5, 1, "黑色", "128GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.36, 4610,
         '["gaming","flagship"]', "骁龙8Gen3，徕卡影像"),
        ("小米14 Pro 黑色 512GB", 5199, 50, "手机", 5199, 5, 1, "黑色", "512GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.73, 4880,
         '["gaming","photography","flagship","business"]', "骁龙8Gen3，超大底主摄"),
        ("红米Note13 蓝色 128GB", 1249, 150, "手机", 1249, 5, 1, "蓝色", "128GB",
         "红米", "天玑6080", "mt", "budget", 6.67, 5000,
         '["budget","student"]', "入门首选，大屏长续航"),
        ("小米平板6 金色 128GB", 2299, 60, "平板", 2299, 5, 1, "金色", "128GB",
         "小米", "骁龙870", "sd", "mid", 11.0, 8840,
         '["student","business"]', "高刷大屏，学习办公利器"),
        ("AirPods Pro 2", 1749, 150, "耳机", 1749, 0, 1, "白色", "",
         "Apple", "", "", "flagship", None, None,
         '["flagship","business"]', "主动降噪，空间音频"),
        ("iPad Air 10寸 64GB", 4599, 40, "平板", 4599, 10, 1, "星光色", "64GB",
         "Apple", "M1", "apple", "flagship", 10.9, None,
         '["student","business"]', "M1芯片，轻薄设计"),
    ],
    "pdd": [
        ("iPhone 15 黑色 128GB", 5750, 200, "手机", 5750, 0, 1, "黑色", "128GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","gaming","flagship"]', "A16芯片，双摄系统"),
        ("iPhone 15 粉色 128GB", 5800, 150, "手机", 5800, 0, 1, "粉色", "128GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","flagship"]', "A16芯片，双摄系统"),
        ("iPhone 15 蓝色 256GB", 6700, 80, "手机", 6700, 0, 1, "蓝色", "256GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","gaming","flagship"]', "A16芯片，双摄系统"),
        ("iPhone 15 Pro 黑色 256GB", 8599, 50, "手机", 8599, 0, 1, "黑色", "256GB",
         "Apple", "A17 Pro", "apple", "flagship", 6.1, 3274,
         '["gaming","photography","flagship","business"]', "A17 Pro芯片，钛金属机身"),
        ("小米14 绿色 256GB", 3899, 200, "手机", 3899, 0, 1, "绿色", "256GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.36, 4610,
         '["gaming","photography","flagship"]', "骁龙8Gen3，徕卡影像"),
        ("小米14 黑色 512GB", 4299, 100, "手机", 4299, 0, 1, "黑色", "512GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.36, 4610,
         '["gaming","flagship"]', "骁龙8Gen3，徕卡影像"),
        ("小米14 Pro 黑色 512GB", 4999, 80, "手机", 4999, 0, 1, "黑色", "512GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.73, 4880,
         '["gaming","photography","flagship","business"]', "骁龙8Gen3，超大底主摄"),
        ("红米Note13 蓝色 128GB", 1199, 300, "手机", 1199, 0, 1, "蓝色", "128GB",
         "红米", "天玑6080", "mt", "budget", 6.67, 5000,
         '["budget","student"]', "入门首选，大屏长续航"),
        ("小米平板6 蓝色 128GB", 2099, 120, "平板", 2099, 0, 1, "蓝色", "128GB",
         "小米", "骁龙870", "sd", "mid", 11.0, 8840,
         '["student","business"]', "高刷大屏，学习办公利器"),
        ("AirPods Pro 2", 1699, 300, "耳机", 1699, 0, 1, "白色", "",
         "Apple", "", "", "flagship", None, None,
         '["flagship","business"]', "主动降噪，空间音频"),
    ],
    "suning": [
        ("iPhone 15 黑色 128GB", 6049, 50, "手机", 6049, 15, 1, "黑色", "128GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","gaming","flagship"]', "A16芯片，双摄系统"),
        ("iPhone 15 白色 256GB", 7049, 30, "手机", 7049, 15, 1, "白色", "256GB",
         "Apple", "A16 Bionic", "apple", "flagship", 6.1, 3279,
         '["photography","flagship"]', "A16芯片，双摄系统"),
        ("iPhone 15 Pro 黑色 256GB", 9099, 20, "手机", 9099, 15, 1, "黑色", "256GB",
         "Apple", "A17 Pro", "apple", "flagship", 6.1, 3274,
         '["gaming","photography","flagship","business"]', "A17 Pro芯片，钛金属机身"),
        ("小米14 白色 128GB", 3949, 60, "手机", 3949, 10, 1, "白色", "128GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.36, 4610,
         '["gaming","flagship"]', "骁龙8Gen3，徕卡影像"),
        ("小米14 金色 256GB", 4149, 50, "手机", 4149, 10, 1, "金色", "256GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.36, 4610,
         '["gaming","photography","flagship"]', "骁龙8Gen3，徕卡影像"),
        ("小米14 Pro 黑色 512GB", 5399, 40, "手机", 5399, 10, 1, "黑色", "512GB",
         "小米", "骁龙8Gen3", "sd", "flagship", 6.73, 4880,
         '["gaming","photography","flagship","business"]', "骁龙8Gen3，超大底主摄"),
        ("红米Note13 蓝色 128GB", 1349, 80, "手机", 1349, 10, 1, "蓝色", "128GB",
         "红米", "天玑6080", "mt", "budget", 6.67, 5000,
         '["budget","student"]', "入门首选，大屏长续航"),
        ("小米平板6 黑色 256GB", 2399, 40, "平板", 2399, 10, 1, "黑色", "256GB",
         "小米", "骁龙870", "sd", "mid", 11.0, 8840,
         '["student","business"]', "高刷大屏，学习办公利器"),
        ("AirPods Pro 2", 1849, 80, "耳机", 1849, 0, 1, "白色", "",
         "Apple", "", "", "flagship", None, None,
         '["flagship","business"]', "主动降噪，空间音频"),
        ("iPad Mini 8寸 64GB", 3999, 25, "平板", 3999, 15, 1, "深空灰", "64GB",
         "Apple", "A15 Bionic", "apple", "flagship", 8.3, None,
         '["student","gaming"]', "小巧便携，A15芯片"),
    ],
}


def init_all_platforms():
    """初始化所有平台的数据库（创建表并插入 Mock 数据）"""
    for platform_id in get_platform_ids():
        db = PlatformDatabase(platform_id)
        mock_data = _PLATFORM_MOCK_DATA.get(platform_id, [])
        db.init_platform_db(mock_data)
        db.close()


# ── 颜色/内存的别名映射 ──────────────────────────────────────────────────────
COLOR_ALIASES: Dict[str, List[str]] = {
    "黑": ["黑", "black", "深空黑", "暗夜黑", "曜石黑", "星际黑", "深空灰"],
    "白": ["白", "white", "星光", "银白", "珍珠白", "陶瓷白", "星光色"],
    "蓝": ["蓝", "blue", "深海蓝", "远峰蓝", "碧湖蓝"],
    "紫": ["紫", "purple", "香芋紫", "幻紫"],
    "粉": ["粉", "pink", "樱花粉", "珊瑚粉"],
    "绿": ["绿", "green", "松针绿", "翡翠绿"],
    "金": ["金", "gold", "香槟金", "沙金"],
    "红": ["红", "red"],
}

MEMORY_ALIASES: Dict[str, List[str]] = {
    "128": ["128gb", "128g", "128"],
    "256": ["256gb", "256g", "256"],
    "512": ["512gb", "512g", "512"],
    "1t": ["1tb", "1t", "1024gb", "1024g"],
}

# ── 处理器别名映射 ──────────────────────────────────────────────────────────

# 处理器厂商归一化别名（key 为 processor_brand 字段的值）
PROCESSOR_BRAND_ALIASES: Dict[str, List[str]] = {
    "sd":    ["骁龙", "snapdragon", "高通", "qualcomm", "soc"],
    "mt":    ["天玑", "dimensity", "联发科", "mediatek"],
    "apple": ["a17", "a16", "a15", "a14", "m2", "m3", "苹果芯片", "apple silicon", "bionic"],
    "kirin": ["麒麟", "kirin", "海思", "hisilicon"],
    "exynos":["猎户座", "exynos"],
}

# 常见处理器型号关键词（用于 processor 字段的 LIKE 匹配）
PROCESSOR_MODEL_KEYWORDS: Dict[str, List[str]] = {
    "8gen3":  ["8gen3", "8 gen 3", "第三代骁龙8"],
    "8gen2":  ["8gen2", "8 gen 2", "第二代骁龙8"],
    "9300":   ["9300", "天玑9300"],
    "9200":   ["9200", "天玑9200"],
    "a17":    ["a17", "a17 pro", "a17 bionic"],
    "a16":    ["a16", "a16 bionic"],
}


def _normalize(text: str) -> str:
    """移除空白和标点，转小写，用于模糊匹配"""
    return re.sub(r"[^\w]", "", str(text)).lower()


def _color_tokens(color_hint: str) -> List[str]:
    """把用户输入的颜色 hint 展开成匹配词列表"""
    hint_norm = _normalize(color_hint)
    for key, aliases in COLOR_ALIASES.items():
        if any(_normalize(a) in hint_norm or hint_norm in _normalize(a) for a in aliases):
            return [_normalize(a) for a in aliases]
    return [hint_norm]


def _memory_tokens(memory_hint: str) -> List[str]:
    """把用户输入的内存 hint 展开成匹配词列表"""
    hint_norm = _normalize(memory_hint)
    for key, aliases in MEMORY_ALIASES.items():
        if any(alias in hint_norm for alias in aliases):
            return aliases
    return [hint_norm]


def _processor_brand_tokens(processor_hint: str) -> List[str]:
    """把用户输入的处理器 hint 映射到 processor_brand key"""
    hint_norm = _normalize(processor_hint)
    for key, aliases in PROCESSOR_BRAND_ALIASES.items():
        if any(_normalize(a) in hint_norm or hint_norm in _normalize(a) for a in aliases):
            return [key]
    return [hint_norm]


def _processor_model_tokens(processor_hint: str) -> Optional[str]:
    """提取处理器型号关键词，用于 LIKE 匹配"""
    hint_norm = _normalize(processor_hint)
    for key, aliases in PROCESSOR_MODEL_KEYWORDS.items():
        if any(_normalize(a) in hint_norm or hint_norm in _normalize(a) for a in aliases):
            return key
    return None

# TIER 排序权重（同分时用于打破平局）
_TIER_RANK = {"flagship": 3, "mid": 2, "budget": 1}


# ── 17 列索引常量（避免硬编码魔法数字） ────────────────────────────────────────
class _COL:
    ID = 0
    PRODUCT_NAME = 1
    PRICE = 2
    STOCK = 3
    CATEGORY = 4
    PLATFORM_PRICE = 5
    SHIPPING_FEE = 6
    IS_IN_STOCK = 7
    COLOR = 8
    MEMORY = 9
    BRAND = 10
    PROCESSOR = 11
    PROCESSOR_BRAND = 12
    PERFORMANCE_TIER = 13
    SCREEN_SIZE = 14
    BATTERY = 15
    USE_CASE_TAGS = 16
    DESCRIPTION = 17


def _row_to_dict(row, platform_id: str, platform_name: str) -> Dict:
    """将 17 列的行元组统一转为字典"""
    return {
        "platform_id": platform_id,
        "platform_name": platform_name,
        "id": row[_COL.ID],
        "product_name": row[_COL.PRODUCT_NAME],
        "price": row[_COL.PRICE],
        "platform_price": row[_COL.PLATFORM_PRICE] or row[_COL.PRICE],
        "stock": row[_COL.STOCK],
        "category": row[_COL.CATEGORY],
        "shipping_fee": row[_COL.SHIPPING_FEE],
        "is_in_stock": bool(row[_COL.IS_IN_STOCK]),
        "color": row[_COL.COLOR],
        "memory": row[_COL.MEMORY],
        "brand": row[_COL.BRAND],
        "processor": row[_COL.PROCESSOR],
        "processor_brand": row[_COL.PROCESSOR_BRAND],
        "performance_tier": row[_COL.PERFORMANCE_TIER],
        "screen_size": row[_COL.SCREEN_SIZE],
        "battery": row[_COL.BATTERY],
        "use_case_tags": row[_COL.USE_CASE_TAGS],
        "description": row[_COL.DESCRIPTION],
    }


class PlatformDatabase:
    """单个平台的数据库管理（含精确属性搜索，17 列 IT3C Schema）"""

    # SELECT 全部 17 个数据列的 SQL 片段
    _SELECT_COLS = (
        "id, product_name, price, stock, category, "
        "platform_price, shipping_fee, is_in_stock, color, memory, "
        "brand, processor, processor_brand, performance_tier, "
        "screen_size, battery, use_case_tags, description"
    )

    def __init__(self, platform_id: str):
        self.platform_id = platform_id
        config = get_platform_config(platform_id)
        self.db_path = config.get("db_path", f"platform_{platform_id}.db")
        self.platform_name = config.get("name", platform_id)
        self._conn = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        return self._conn

    def get_cursor(self):
        return self.connect().cursor()

    def commit(self):
        if self._conn:
            self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def init_platform_db(self, mock_data: List[tuple]):
        """初始化平台数据库 — DROP+CREATE 保证 Schema 一致性，幂等"""
        cursor = self.get_cursor()

        # DROP + CREATE 确保 Schema 始终是最新的（mock 数据场景下可接受）
        cursor.execute("DROP TABLE IF EXISTS products")
        cursor.execute('''
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                price REAL NOT NULL,
                stock INTEGER NOT NULL,
                category TEXT NOT NULL,
                platform_price REAL,
                shipping_fee REAL DEFAULT 0,
                is_in_stock BOOLEAN DEFAULT 1,
                color TEXT,
                memory TEXT,
                brand TEXT,
                processor TEXT,
                processor_brand TEXT,
                performance_tier TEXT,
                screen_size REAL,
                battery INTEGER,
                use_case_tags TEXT,
                description TEXT
            )
        ''')

        cursor.execute("SELECT COUNT(*) FROM products")
        existing_count = cursor.fetchone()[0]
        if existing_count > 0:
            print(f"✓ {self.platform_name}数据库已存在 {existing_count} 条数据，跳过初始化")
            return

        cursor.executemany(
            """INSERT INTO products
               (product_name, price, stock, category, platform_price, shipping_fee,
                is_in_stock, color, memory, brand, processor, processor_brand,
                performance_tier, screen_size, battery, use_case_tags, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            mock_data,
        )
        self.commit()
        print(f"✓ {self.platform_name}数据库初始化完成，插入{len(mock_data)}个商品")

    # ── 结构化属性查询 ──────────────────────────────────────────────────────

    def query_product_by_attrs(
        self,
        product_name: str,
        color: Optional[str] = None,
        memory: Optional[str] = None,
        category: Optional[str] = None,
        processor_brand: Optional[str] = None,
        processor_hint: Optional[str] = None,
        use_case: Optional[str] = None,
        performance_tier: Optional[str] = None,
        budget_max: Optional[float] = None,
        budget_min: Optional[float] = None,
    ) -> Optional[Dict]:
        """精确属性查询。返回最佳匹配的单条商品（6 维评分）。"""
        cursor = self.get_cursor()

        color_tokens = _color_tokens(color) if color else []
        memory_tokens = _memory_tokens(memory) if memory else []
        pb_tokens = _processor_brand_tokens(processor_hint) if processor_hint else []
        pm_token = _processor_model_tokens(processor_hint) if processor_hint else None

        base_sql = f"""
            SELECT {self._SELECT_COLS}
            FROM products
            WHERE product_name LIKE ?
        """
        params = [f"%{product_name}%"]

        if category:
            base_sql += " AND category LIKE ?"
            params.append(f"%{category}%")
        if budget_max is not None:
            base_sql += " AND price <= ?"
            params.append(budget_max)
        if budget_min is not None:
            base_sql += " AND price >= ?"
            params.append(budget_min)

        cursor.execute(base_sql, params)
        candidates = cursor.fetchall()

        if not candidates:
            return self._fuzzy_match(product_name)

        def score(row) -> Tuple[int, int, float, dict]:
            s = 0
            row_color = _normalize(row[_COL.COLOR] or "")
            row_memory = _normalize(row[_COL.MEMORY] or "")
            row_pb = _normalize(row[_COL.PROCESSOR_BRAND] or "")
            row_proc = _normalize(row[_COL.PROCESSOR] or "")
            row_tier = row[_COL.PERFORMANCE_TIER] or ""
            row_tags = row[_COL.USE_CASE_TAGS] or "[]"
            row_price = row[_COL.PLATFORM_PRICE] or row[_COL.PRICE]

            if color_tokens and any(t in row_color for t in color_tokens):
                s += 1
            if memory_tokens and any(t in row_memory for t in memory_tokens):
                s += 1
            if pb_tokens and any(t in row_pb for t in pb_tokens):
                s += 1
            if pm_token and pm_token in row_proc:
                s += 1
            if use_case and use_case.strip():
                # 每个指定的 use_case 标签都要在 tags 中
                tags_lower = row_tags.lower()
                if all(tag.strip().lower() in tags_lower for tag in use_case.split(",")):
                    s += 1
            if performance_tier and _normalize(performance_tier) == _normalize(row_tier):
                s += 1

            tier_rank = _TIER_RANK.get(row_tier, 0)
            return s, tier_rank, -row_price, _row_to_dict(row, self.platform_id, self.platform_name)

        # 主排序：score DESC → tier_rank DESC → price ASC
        scored = sorted([score(r) for r in candidates], key=lambda x: (x[0], x[1], x[2]), reverse=True)
        best_score, _, _, best_result = scored[0]
        best_result["_match_score"] = best_score
        return best_result

    def query_products_by_attrs(
        self,
        product_name: str,
        color: Optional[str] = None,
        memory: Optional[str] = None,
        category: Optional[str] = None,
        processor_brand: Optional[str] = None,
        processor_hint: Optional[str] = None,
        use_case: Optional[str] = None,
        performance_tier: Optional[str] = None,
        budget_max: Optional[float] = None,
        budget_min: Optional[float] = None,
    ) -> List[Dict]:
        """返回所有匹配的候选商品，按 6 维评分降序排列。"""
        cursor = self.get_cursor()

        color_tokens = _color_tokens(color) if color else []
        memory_tokens = _memory_tokens(memory) if memory else []
        pb_tokens = _processor_brand_tokens(processor_hint) if processor_hint else []
        pm_token = _processor_model_tokens(processor_hint) if processor_hint else None

        base_sql = f"""
            SELECT {self._SELECT_COLS}
            FROM products
            WHERE product_name LIKE ?
        """
        params = [f"%{product_name}%"]

        if category:
            base_sql += " AND category LIKE ?"
            params.append(f"%{category}%")
        if budget_max is not None:
            base_sql += " AND price <= ?"
            params.append(budget_max)
        if budget_min is not None:
            base_sql += " AND price >= ?"
            params.append(budget_min)

        cursor.execute(base_sql, params)
        candidates = cursor.fetchall()

        if not candidates:
            return self._fuzzy_match_all(product_name)

        def score(row) -> Tuple[int, int, float, dict]:
            s = 0
            row_color = _normalize(row[_COL.COLOR] or "")
            row_memory = _normalize(row[_COL.MEMORY] or "")
            row_pb = _normalize(row[_COL.PROCESSOR_BRAND] or "")
            row_proc = _normalize(row[_COL.PROCESSOR] or "")
            row_tier = row[_COL.PERFORMANCE_TIER] or ""
            row_tags = row[_COL.USE_CASE_TAGS] or "[]"
            row_price = row[_COL.PLATFORM_PRICE] or row[_COL.PRICE]

            if color_tokens and any(t in row_color for t in color_tokens):
                s += 1
            if memory_tokens and any(t in row_memory for t in memory_tokens):
                s += 1
            if pb_tokens and any(t in row_pb for t in pb_tokens):
                s += 1
            if pm_token and pm_token in row_proc:
                s += 1
            if use_case and use_case.strip():
                tags_lower = row_tags.lower()
                if all(tag.strip().lower() in tags_lower for tag in use_case.split(",")):
                    s += 1
            if performance_tier and _normalize(performance_tier) == _normalize(row_tier):
                s += 1

            tier_rank = _TIER_RANK.get(row_tier, 0)
            return s, tier_rank, -row_price, _row_to_dict(row, self.platform_id, self.platform_name)

        scored = sorted([score(r) for r in candidates], key=lambda x: (x[0], x[1], x[2]), reverse=True)
        results = []
        for s, _, _, d in scored:
            d["_match_score"] = s
            results.append(d)
        return results

    def _fuzzy_match_all(self, product_name: str) -> List[Dict]:
        """模糊匹配兜底：返回所有 product_name 子串匹配的商品"""
        cursor = self.get_cursor()
        cursor.execute(f"SELECT {self._SELECT_COLS} FROM products")
        all_products = cursor.fetchall()
        norm_query = _normalize(product_name)
        results = []
        for p in all_products:
            norm_p = _normalize(p[_COL.PRODUCT_NAME])
            if norm_query in norm_p or norm_p in norm_query:
                results.append(_row_to_dict(p, self.platform_id, self.platform_name))
        return results

    def _fuzzy_match(self, product_name: str) -> Optional[Dict]:
        """原有规范化模糊匹配逻辑（兜底）"""
        cursor = self.get_cursor()
        cursor.execute(f"SELECT {self._SELECT_COLS} FROM products")
        all_products = cursor.fetchall()
        norm_query = _normalize(product_name)
        for p in all_products:
            norm_p = _normalize(p[_COL.PRODUCT_NAME])
            if norm_query in norm_p or norm_p in norm_query:
                return _row_to_dict(p, self.platform_id, self.platform_name)
        return None

    def query_product(self, product_name: str) -> Optional[Dict]:
        """向后兼容：原接口委托给 query_product_by_attrs()"""
        return self.query_product_by_attrs(product_name)

    def update_product(
        self,
        product_id: int,
        product_name: Optional[str] = None,
        price: Optional[float] = None,
        stock: Optional[int] = None,
        category: Optional[str] = None,
        platform_price: Optional[float] = None,
        shipping_fee: Optional[float] = None,
        is_in_stock: Optional[bool] = None,
        color: Optional[str] = None,
        memory: Optional[str] = None,
    ) -> Optional[Dict]:
        cursor = self.get_cursor()
        cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        existing = cursor.fetchone()
        if not existing:
            return None

        fields = {
            "product_name": product_name if product_name is not None else existing[1],
            "price": price if price is not None else existing[2],
            "stock": stock if stock is not None else existing[3],
            "category": category if category is not None else existing[4],
            "platform_price": platform_price if platform_price is not None else existing[5],
            "shipping_fee": shipping_fee if shipping_fee is not None else existing[6],
            "is_in_stock": is_in_stock if is_in_stock is not None else existing[7],
            "color": color if color is not None else existing[8],
            "memory": memory if memory is not None else existing[9],
        }

        cursor.execute(
            """UPDATE products
               SET product_name=?, price=?, stock=?, category=?,
                   platform_price=?, shipping_fee=?, is_in_stock=?, color=?, memory=?
               WHERE id=?""",
            (fields["product_name"], fields["price"], fields["stock"], fields["category"],
             fields["platform_price"], fields["shipping_fee"], fields["is_in_stock"],
             fields["color"], fields["memory"], product_id),
        )
        self.commit()
        return {
            "platform_id": self.platform_id,
            "platform_name": self.platform_name,
            "id": product_id,
            **fields,
        }

    def delete_product(self, product_id: int) -> bool:
        cursor = self.get_cursor()
        cursor.execute("SELECT id FROM products WHERE id = ?", (product_id,))
        if not cursor.fetchone():
            return False
        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
        self.commit()
        return True

    def query_all_products(self) -> List[Dict]:
        cursor = self.get_cursor()
        cursor.execute(f"SELECT {self._SELECT_COLS} FROM products")
        rows = cursor.fetchall()
        return [_row_to_dict(r, self.platform_id, self.platform_name) for r in rows]

    def add_product(
        self,
        product_name: str,
        price: float,
        stock: int,
        category: str,
        platform_price: Optional[float] = None,
        shipping_fee: float = 0,
        is_in_stock: bool = True,
        color: Optional[str] = None,
        memory: Optional[str] = None,
    ) -> Dict:
        """添加商品到平台数据库"""
        cursor = self.get_cursor()
        cursor.execute(
            """INSERT INTO products
               (product_name, price, stock, category, platform_price, shipping_fee,
                is_in_stock, color, memory)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (product_name, price, stock, category, platform_price or price,
             shipping_fee, is_in_stock, color, memory),
        )
        self.commit()
        product_id = cursor.lastrowid
        return {
            "id": product_id,
            "platform_id": self.platform_id,
            "platform_name": self.platform_name,
            "product_name": product_name,
            "price": price,
            "platform_price": platform_price or price,
            "stock": stock,
            "category": category,
            "shipping_fee": shipping_fee,
            "is_in_stock": is_in_stock,
            "color": color,
            "memory": memory,
        }
