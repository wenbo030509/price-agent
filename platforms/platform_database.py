"""
platforms/platform_database.py  —— 修复版本
修复点（Fix-3）：商品搜索精度
  - 新增 query_product_by_attrs()：支持结构化属性过滤（color/memory/brand）
  - 原 query_product() 保留，改为调用新方法（向后兼容）
  - 新增 LLM 属性解析工具函数 parse_query_attrs()（在 tools 层调用）
"""

import re
import sqlite3
from typing import Dict, List, Optional, Tuple

from .platform_config import get_platform_config, get_platform_ids


# ── 各平台 Mock 数据 ────────────────────────────────────────────────────────
_PLATFORM_MOCK_DATA = {
    "jd": [
        ("iPhone 15 黑色 128GB", 5999, 100, "手机", 5999, 0, 1, "黑色", "128GB"),
        ("iPhone 15 白色 128GB", 5999, 80, "手机", 5999, 0, 1, "白色", "128GB"),
        ("iPhone 15 黑色 256GB", 6999, 50, "手机", 6999, 0, 1, "黑色", "256GB"),
        ("iPhone 15 白色 256GB", 6999, 60, "手机", 6999, 0, 1, "白色", "256GB"),
        ("小米14 黑色 256GB", 3999, 150, "手机", 3999, 0, 1, "黑色", "256GB"),
        ("小米14 白色 256GB", 4099, 120, "手机", 4099, 0, 1, "白色", "256GB"),
        ("小米平板6 黑色 128GB", 2199, 100, "平板", 2199, 0, 1, "黑色", "128GB"),
        ("小米平板6 白色 128GB", 2199, 80, "平板", 2199, 0, 1, "白色", "128GB"),
        ("AirPods Pro 2", 1799, 200, "耳机", 1799, 0, 1, "白色", ""),
        ("iPad Pro 11寸 256GB", 7999, 30, "平板", 7999, 0, 1, "深空灰", "256GB"),
    ],
    "taobao": [
        ("iPhone 15 黑色 128GB", 5899, 90, "手机", 5899, 10, 1, "黑色", "128GB"),
        ("iPhone 15 蓝色 128GB", 5950, 70, "手机", 5950, 10, 1, "蓝色", "128GB"),
        ("iPhone 15 黑色 256GB", 6850, 40, "手机", 6850, 10, 1, "黑色", "256GB"),
        ("小米14 紫色 256GB", 3999, 100, "手机", 3999, 5, 1, "紫色", "256GB"),
        ("小米14 黑色 128GB", 3799, 80, "手机", 3799, 5, 1, "黑色", "128GB"),
        ("小米平板6 金色 128GB", 2299, 60, "平板", 2299, 5, 1, "金色", "128GB"),
        ("AirPods Pro 2", 1749, 150, "耳机", 1749, 0, 1, "白色", ""),
        ("iPad Air 10寸 64GB", 4599, 40, "平板", 4599, 10, 1, "星光色", "64GB"),
    ],
    "pdd": [
        ("iPhone 15 黑色 128GB", 5750, 200, "手机", 5750, 0, 1, "黑色", "128GB"),
        ("iPhone 15 粉色 128GB", 5800, 150, "手机", 5800, 0, 1, "粉色", "128GB"),
        ("iPhone 15 蓝色 256GB", 6700, 80, "手机", 6700, 0, 1, "蓝色", "256GB"),
        ("小米14 绿色 256GB", 3899, 200, "手机", 3899, 0, 1, "绿色", "256GB"),
        ("小米14 黑色 512GB", 4299, 100, "手机", 4299, 0, 1, "黑色", "512GB"),
        ("小米平板6 蓝色 128GB", 2099, 120, "平板", 2099, 0, 1, "蓝色", "128GB"),
        ("AirPods Pro 2", 1699, 300, "耳机", 1699, 0, 1, "白色", ""),
    ],
    "suning": [
        ("iPhone 15 黑色 128GB", 6049, 50, "手机", 6049, 15, 1, "黑色", "128GB"),
        ("iPhone 15 白色 256GB", 7049, 30, "手机", 7049, 15, 1, "白色", "256GB"),
        ("小米14 白色 128GB", 3949, 60, "手机", 3949, 10, 1, "白色", "128GB"),
        ("小米14 金色 256GB", 4149, 50, "手机", 4149, 10, 1, "金色", "256GB"),
        ("小米平板6 黑色 256GB", 2399, 40, "平板", 2399, 10, 1, "黑色", "256GB"),
        ("AirPods Pro 2", 1849, 80, "耳机", 1849, 0, 1, "白色", ""),
        ("iPad Mini 8寸 64GB", 3999, 25, "平板", 3999, 15, 1, "深空灰", "64GB"),
    ],
}


def init_all_platforms():
    """初始化所有平台的数据库（创建表并插入 Mock 数据）"""
    for platform_id in get_platform_ids():
        db = PlatformDatabase(platform_id)
        mock_data = _PLATFORM_MOCK_DATA.get(platform_id, [])
        db.init_platform_db(mock_data)
        db.close()


# ── 颜色/内存的别名映射（扩充后搜索更准） ──────────────────────────────────
COLOR_ALIASES: Dict[str, List[str]] = {
    "黑": ["黑", "black", "深空黑", "暗夜黑", "曜石黑", "星际黑"],
    "白": ["白", "white", "星光", "银白", "珍珠白", "陶瓷白"],
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


class PlatformDatabase:
    """单个平台的数据库管理（含精确属性搜索）"""

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
        cursor = self.get_cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                price REAL NOT NULL,
                stock INTEGER NOT NULL,
                category TEXT NOT NULL,
                platform_price REAL,
                shipping_fee REAL DEFAULT 0,
                is_in_stock BOOLEAN DEFAULT 1,
                color TEXT,
                memory TEXT
            )
        ''')

        cursor.execute("SELECT COUNT(*) FROM products")
        existing_count = cursor.fetchone()[0]
        if existing_count > 0:
            print(f"✓ {self.platform_name}数据库已存在 {existing_count} 条数据，跳过初始化")
            return

        cursor.executemany(
            """INSERT INTO products
               (product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            mock_data,
        )
        self.commit()
        print(f"✓ {self.platform_name}数据库初始化完成，插入{len(mock_data)}个商品")

    # ──────────────────────────────────────────────────────────────────────
    # Fix-3: 结构化属性查询（核心新增方法）
    # ──────────────────────────────────────────────────────────────────────
    def query_product_by_attrs(
        self,
        product_name: str,
        color: Optional[str] = None,
        memory: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        精确属性查询。

        查询策略（优先级从高到低）：
          1. product_name LIKE + color 精确 + memory 精确（三者都匹配）
          2. product_name LIKE + color 精确（忽略 memory）
          3. product_name LIKE + memory 精确（忽略 color）
          4. 退化到纯 product_name 模糊匹配（原逻辑兜底）

        参数
        ----
        product_name : str  必填，商品名称关键词
        color        : str  可选，颜色，如 "黑色"、"黑"
        memory       : str  可选，内存/容量，如 "256GB"、"256"
        category     : str  可选，品类过滤，如 "手机"
        """
        cursor = self.get_cursor()

        # 预处理属性 hint
        color_tokens = _color_tokens(color) if color else []
        memory_tokens = _memory_tokens(memory) if memory else []

        # 取所有 product_name 匹配的候选商品
        base_sql = """
            SELECT id, product_name, price, stock, category,
                   platform_price, shipping_fee, is_in_stock, color, memory
            FROM products
            WHERE product_name LIKE ?
        """
        params = [f"%{product_name}%"]

        if category:
            base_sql += " AND category LIKE ?"
            params.append(f"%{category}%")

        cursor.execute(base_sql, params)
        candidates = cursor.fetchall()

        if not candidates:
            # 退化到规范化模糊匹配
            return self._fuzzy_match(product_name)

        def row_to_dict(row) -> Dict:
            return {
                "platform_id": self.platform_id,
                "platform_name": self.platform_name,
                "id": row[0],
                "product_name": row[1],
                "price": row[2],
                "platform_price": row[5] or row[2],
                "stock": row[3],
                "category": row[4],
                "shipping_fee": row[6],
                "is_in_stock": bool(row[7]),
                "color": row[8],
                "memory": row[9],
            }

        def score(row) -> Tuple[int, float, dict]:
            """
            计算候选商品与属性条件的匹配分数（越高越好）。
            color 和 memory 各贡献 1 分。
            同分时按 platform_price 升序打破平局。
            """
            s = 0
            row_color = _normalize(row[8] or "")
            row_memory = _normalize(row[9] or "")

            if color_tokens and any(t in row_color for t in color_tokens):
                s += 1
            if memory_tokens and any(t in row_memory for t in memory_tokens):
                s += 1
            return s, -(row[5] or row[2]), row_to_dict(row)

        # 按分数降序、价格升序排列，取最佳匹配
        scored = sorted([score(r) for r in candidates], key=lambda x: (x[0], x[1]), reverse=True)
        best_score, _, best_result = scored[0]
        best_result["_match_score"] = best_score

        # 至少 product_name 匹配就返回（分数 0 也行，作为兜底）
        return best_result

    def query_products_by_attrs(
        self,
        product_name: str,
        color: Optional[str] = None,
        memory: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict]:
        """
        返回所有匹配的候选商品，按匹配分数降序排列。
        当用户查询模糊时（如"手机"、"iPhone"），可返回所有匹配结果。
        """
        cursor = self.get_cursor()

        color_tokens = _color_tokens(color) if color else []
        memory_tokens = _memory_tokens(memory) if memory else []

        base_sql = """
            SELECT id, product_name, price, stock, category,
                   platform_price, shipping_fee, is_in_stock, color, memory
            FROM products
            WHERE product_name LIKE ?
        """
        params = [f"%{product_name}%"]

        if category:
            base_sql += " AND category LIKE ?"
            params.append(f"%{category}%")

        cursor.execute(base_sql, params)
        candidates = cursor.fetchall()

        if not candidates:
            return self._fuzzy_match_all(product_name)

        def row_to_dict(row) -> Dict:
            return {
                "platform_id": self.platform_id,
                "platform_name": self.platform_name,
                "id": row[0],
                "product_name": row[1],
                "price": row[2],
                "platform_price": row[5] or row[2],
                "stock": row[3],
                "category": row[4],
                "shipping_fee": row[6],
                "is_in_stock": bool(row[7]),
                "color": row[8],
                "memory": row[9],
            }

        def score(row) -> Tuple[int, float, dict]:
            s = 0
            row_color = _normalize(row[8] or "")
            row_memory = _normalize(row[9] or "")
            if color_tokens and any(t in row_color for t in color_tokens):
                s += 1
            if memory_tokens and any(t in row_memory for t in memory_tokens):
                s += 1
            return s, -(row[5] or row[2]), row_to_dict(row)

        scored = sorted([score(r) for r in candidates], key=lambda x: (x[0], x[1]), reverse=True)
        results = []
        for s, _, d in scored:
            d["_match_score"] = s
            results.append(d)
        return results

    def _fuzzy_match_all(self, product_name: str) -> List[Dict]:
        """模糊匹配兜底：返回所有 product_name 子串匹配的商品"""
        cursor = self.get_cursor()
        cursor.execute(
            "SELECT id, product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory FROM products"
        )
        all_products = cursor.fetchall()
        norm_query = _normalize(product_name)
        results = []
        for p in all_products:
            norm_p = _normalize(p[1])
            if norm_query in norm_p or norm_p in norm_query:
                results.append({
                    "platform_id": self.platform_id,
                    "platform_name": self.platform_name,
                    "id": p[0],
                    "product_name": p[1],
                    "price": p[2],
                    "platform_price": p[5] or p[2],
                    "stock": p[3],
                    "category": p[4],
                    "shipping_fee": p[6],
                    "is_in_stock": bool(p[7]),
                    "color": p[8],
                    "memory": p[9],
                })
        return results

    def _fuzzy_match(self, product_name: str) -> Optional[Dict]:
        """原有规范化模糊匹配逻辑（兜底）"""
        cursor = self.get_cursor()
        cursor.execute(
            "SELECT id, product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory FROM products"
        )
        all_products = cursor.fetchall()
        norm_query = _normalize(product_name)
        for p in all_products:
            norm_p = _normalize(p[1])
            if norm_query in norm_p or norm_p in norm_query:
                return {
                    "platform_id": self.platform_id,
                    "platform_name": self.platform_name,
                    "id": p[0],
                    "product_name": p[1],
                    "price": p[2],
                    "platform_price": p[5] or p[2],
                    "stock": p[3],
                    "category": p[4],
                    "shipping_fee": p[6],
                    "is_in_stock": bool(p[7]),
                    "color": p[8],
                    "memory": p[9],
                }
        return None

    # 向后兼容：原 query_product() 委托给新方法
    def query_product(self, product_name: str) -> Optional[Dict]:
        """
        原接口保持不变（向后兼容），内部委托给 query_product_by_attrs()。
        调用方可直接升级为 query_product_by_attrs() 传入 color/memory 获得更精确结果。
        """
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
        cursor.execute(
            """SELECT id, product_name, price, stock, category,
                      platform_price, shipping_fee, is_in_stock, color, memory
               FROM products"""
        )
        rows = cursor.fetchall()
        return [
            {
                "platform_id": self.platform_id,
                "platform_name": self.platform_name,
                "id": r[0],
                "product_name": r[1],
                "price": r[2],
                "platform_price": r[5] or r[2],
                "stock": r[3],
                "category": r[4],
                "shipping_fee": r[6],
                "is_in_stock": bool(r[7]),
                "color": r[8],
                "memory": r[9],
            }
            for r in rows
        ]

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
               (product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (product_name, price, stock, category, platform_price or price, shipping_fee, is_in_stock, color, memory),
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
