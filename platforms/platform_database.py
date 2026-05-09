"""
多平台数据库管理
创建和管理各个电商平台的数据库
"""
import sqlite3
from typing import List, Dict, Optional
from .platform_config import get_platform_config, get_all_platforms


class PlatformDatabase:
    """单个平台的数据库管理"""
    
    def __init__(self, platform_id: str):
        self.platform_id = platform_id
        config = get_platform_config(platform_id)
        self.db_path = config.get("db_path", f"platform_{platform_id}.db")
        self.platform_name = config.get("name", platform_id)
        self._conn = None
    
    def connect(self) -> sqlite3.Connection:
        """连接数据库"""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        return self._conn
    
    def get_cursor(self):
        """获取游标"""
        conn = self.connect()
        return conn.cursor()
    
    def commit(self):
        """提交事务"""
        if self._conn:
            self._conn.commit()
    
    def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def init_platform_db(self, mock_data: List[tuple]):
        """
        初始化平台数据库
        :param mock_data: Mock商品数据列表
        """
        cursor = self.get_cursor()
        
        # 创建商品表
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
        
        # 清空旧数据
        cursor.execute("DELETE FROM products")
        
        # 插入Mock数据
        cursor.executemany(
            """INSERT INTO products 
               (product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            mock_data
        )
        
        self.commit()
        print(f"✓ {self.platform_name}数据库初始化完成，插入{len(mock_data)}个商品")
    
    def _normalize_text(self, text: str) -> str:
        """
        规范化文本，移除空格、符号，转为小写
        """
        import re
        # 移除所有非字母数字字符
        text = re.sub(r'[^\w]', '', text)
        # 转为小写
        return text.lower()
    
    def query_product(self, product_name: str) -> Optional[Dict]:
        """
        查询商品信息（智能匹配）
        :param product_name: 商品名称
        :return: 商品信息字典
        """
        cursor = self.get_cursor()
        
        # 首先尝试精确的LIKE匹配
        cursor.execute(
            """SELECT id, product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory 
               FROM products 
               WHERE product_name LIKE ?""",
            (f"%{product_name}%",)
        )
        result = cursor.fetchone()
        
        if result:
            return {
                "platform_id": self.platform_id,
                "platform_name": self.platform_name,
                "id": result[0],
                "product_name": result[1],
                "price": result[2],
                "platform_price": result[5] or result[2],
                "stock": result[3],
                "category": result[4],
                "shipping_fee": result[6],
                "is_in_stock": bool(result[7]),
                "color": result[8],
                "memory": result[9]
            }
        
        # 如果LIKE没找到，尝试更宽松的匹配（规范化后比较）
        cursor.execute(
            """SELECT id, product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory 
               FROM products"""
        )
        all_products = cursor.fetchall()
        
        normalized_query = self._normalize_text(product_name)
        
        for product in all_products:
            normalized_product = self._normalize_text(product[1])
            if normalized_query in normalized_product or normalized_product in normalized_query:
                return {
                    "platform_id": self.platform_id,
                    "platform_name": self.platform_name,
                    "id": product[0],
                    "product_name": product[1],
                    "price": product[2],
                    "platform_price": product[5] or product[2],
                    "stock": product[3],
                    "category": product[4],
                    "shipping_fee": product[6],
                    "is_in_stock": bool(product[7]),
                    "color": product[8],
                    "memory": product[9]
                }
        
        return None
    
    def query_all_products(self) -> List[Dict]:
        """
        查询所有商品
        :return: 商品列表
        """
        cursor = self.get_cursor()
        cursor.execute(
            """SELECT id, product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory 
               FROM products 
               ORDER BY price"""
        )
        results = cursor.fetchall()
        
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
                "memory": r[9]
            }
            for r in results
        ]
    
    def add_product(self, product_name: str, price: float, stock: int, category: str,
                   platform_price: float = None, shipping_fee: float = 0, is_in_stock: bool = True,
                   color: str = None, memory: str = None) -> Dict:
        """
        添加商品
        :return: 添加的商品信息
        """
        cursor = self.get_cursor()
        cursor.execute(
            """INSERT INTO products 
               (product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (product_name, price, stock, category, platform_price, shipping_fee, 
             1 if is_in_stock else 0, color, memory)
        )
        product_id = cursor.lastrowid
        self.commit()
        
        return {
            "platform_id": self.platform_id,
            "platform_name": self.platform_name,
            "id": product_id,
            "product_name": product_name,
            "price": price,
            "platform_price": platform_price or price,
            "stock": stock,
            "category": category,
            "shipping_fee": shipping_fee,
            "is_in_stock": is_in_stock,
            "color": color,
            "memory": memory
        }
    
    def update_product(self, product_id: int, product_name: str = None, price: float = None,
                      stock: int = None, category: str = None, platform_price: float = None,
                      shipping_fee: float = None, is_in_stock: bool = None,
                      color: str = None, memory: str = None) -> Optional[Dict]:
        """
        更新商品
        :return: 更新后的商品信息，如果商品不存在返回None
        """
        cursor = self.get_cursor()
        
        # 先检查商品是否存在
        cursor.execute("SELECT id FROM products WHERE id = ?", (product_id,))
        if not cursor.fetchone():
            return None
        
        # 构建更新语句
        update_fields = []
        update_values = []
        
        if product_name is not None:
            update_fields.append("product_name = ?")
            update_values.append(product_name)
        if price is not None:
            update_fields.append("price = ?")
            update_values.append(price)
        if stock is not None:
            update_fields.append("stock = ?")
            update_values.append(stock)
        if category is not None:
            update_fields.append("category = ?")
            update_values.append(category)
        if platform_price is not None:
            update_fields.append("platform_price = ?")
            update_values.append(platform_price)
        if shipping_fee is not None:
            update_fields.append("shipping_fee = ?")
            update_values.append(shipping_fee)
        if is_in_stock is not None:
            update_fields.append("is_in_stock = ?")
            update_values.append(1 if is_in_stock else 0)
        if color is not None:
            update_fields.append("color = ?")
            update_values.append(color)
        if memory is not None:
            update_fields.append("memory = ?")
            update_values.append(memory)
        
        if update_fields:
            update_values.append(product_id)
            cursor.execute(
                f"UPDATE products SET {', '.join(update_fields)} WHERE id = ?",
                update_values
            )
            self.commit()
        
        # 返回更新后的商品
        return self.get_product_by_id(product_id)
    
    def get_product_by_id(self, product_id: int) -> Optional[Dict]:
        """
        根据ID获取商品
        """
        cursor = self.get_cursor()
        cursor.execute(
            """SELECT id, product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory 
               FROM products 
               WHERE id = ?""",
            (product_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return {
                "platform_id": self.platform_id,
                "platform_name": self.platform_name,
                "id": result[0],
                "product_name": result[1],
                "price": result[2],
                "platform_price": result[5] or result[2],
                "stock": result[3],
                "category": result[4],
                "shipping_fee": result[6],
                "is_in_stock": bool(result[7]),
                "color": result[8],
                "memory": result[9]
            }
        return None
    
    def delete_product(self, product_id: int) -> bool:
        """
        删除商品
        :return: 是否成功删除
        """
        cursor = self.get_cursor()
        cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
        self.commit()
        return cursor.rowcount > 0


def init_all_platforms():
    """初始化所有平台的数据库"""
    # 各个平台的Mock数据（价格有差异）
    # 格式: (product_name, price, stock, category, platform_price, shipping_fee, is_in_stock, color, memory)
    platform_data = {
        "jd": [
            ("iPhone 15", 5999, 100, "手机", 5999, 0, True, "黑色", "128GB"),
            ("iPhone 15", 6499, 80, "手机", 6499, 0, True, "白色", "256GB"),
            ("iPhone 15 Pro", 8999, 60, "手机", 8899, 0, True, "钛金属黑", "256GB"),
            ("小米14", 3999, 150, "手机", 3949, 0, True, "黑色", "128GB"),
            ("小米14", 4299, 120, "手机", 4249, 0, True, "白色", "256GB"),
            ("华为Mate60", 4999, 80, "手机", 4899, 6, True, "雅丹黑", "256GB"),
            ("华为Mate60 Pro", 6999, 50, "手机", 6899, 6, True, "白沙银", "512GB"),
            ("iPad Pro", 6299, 50, "平板", 6199, 0, True, "深空灰", "128GB"),
            ("iPad Pro", 7499, 35, "平板", 7399, 0, True, "银色", "256GB"),
            ("小米平板6", 2199, 120, "平板", 2149, 0, True, "黑色", "128GB"),
            ("小米平板6 Pro", 2699, 90, "平板", 2649, 0, True, "金色", "256GB"),
            ("MacBook Pro 14", 14999, 30, "电脑", 14899, 0, True, "深空灰", "512GB"),
            ("AirPods Pro", 1899, 200, "配件", 1849, 0, True, None, None)
        ],
        "taobao": [
            ("iPhone 15", 5899, 80, "手机", 5899, 10, True, "黑色", "128GB"),
            ("iPhone 15", 6399, 70, "手机", 6399, 10, True, "粉色", "256GB"),
            ("iPhone 15 Pro", 8899, 55, "手机", 8799, 10, True, "钛金属白", "256GB"),
            ("小米14", 3899, 120, "手机", 3899, 8, True, "粉色", "128GB"),
            ("小米14", 4199, 100, "手机", 4199, 8, True, "蓝色", "256GB"),
            ("华为Mate60", 4899, 60, "手机", 4799, 12, True, "青衫绿", "256GB"),
            ("华为Mate60 Pro", 6899, 45, "手机", 6799, 12, True, "南糯紫", "512GB"),
            ("iPad Pro", 6199, 40, "平板", 6099, 0, True, "银色", "128GB"),
            ("iPad Pro", 7399, 30, "平板", 7299, 0, True, "深空灰", "256GB"),
            ("小米平板6", 2099, 100, "平板", 2049, 6, True, "蓝色", "128GB"),
            ("小米平板6 Pro", 2599, 80, "平板", 2549, 6, True, "绿色", "256GB"),
            ("MacBook Pro 14", 14799, 25, "电脑", 14699, 0, True, "银色", "512GB"),
            ("AirPods Pro", 1799, 180, "配件", 1749, 0, True, None, None)
        ],
        "pdd": [
            ("iPhone 15", 5799, 120, "手机", 5699, 0, True, "黑色", "128GB"),
            ("iPhone 15", 6299, 100, "手机", 6199, 0, True, "白色", "256GB"),
            ("iPhone 15 Pro", 8799, 65, "手机", 8699, 0, True, "钛金属黑", "256GB"),
            ("小米14", 3799, 180, "手机", 3699, 0, True, "白色", "128GB"),
            ("小米14", 4099, 150, "手机", 3999, 0, True, "黑色", "256GB"),
            ("华为Mate60", 4799, 100, "手机", 4699, 0, True, "雅丹黑", "256GB"),
            ("华为Mate60 Pro", 6799, 55, "手机", 6699, 0, True, "白沙银", "512GB"),
            ("iPad Pro", 6099, 60, "平板", 5999, 0, True, "深空灰", "128GB"),
            ("iPad Pro", 7299, 45, "平板", 7199, 0, True, "银色", "256GB"),
            ("小米平板6", 1999, 150, "平板", 1899, 0, True, "黑色", "128GB"),
            ("小米平板6 Pro", 2499, 110, "平板", 2399, 0, True, "金色", "256GB"),
            ("MacBook Pro 14", 14599, 35, "电脑", 14499, 0, True, "深空灰", "512GB"),
            ("AirPods Pro", 1699, 220, "配件", 1599, 0, True, None, None)
        ],
        "suning": [
            ("iPhone 15", 5949, 90, "手机", 5949, 0, True, "黑色", "128GB"),
            ("iPhone 15", 6449, 75, "手机", 6449, 0, True, "白色", "256GB"),
            ("iPhone 15 Pro", 8949, 58, "手机", 8899, 0, True, "钛金属黑", "256GB"),
            ("小米14", 3949, 140, "手机", 3899, 0, True, "黑色", "128GB"),
            ("小米14", 4249, 110, "手机", 4199, 0, True, "白色", "256GB"),
            ("华为Mate60", 4949, 70, "手机", 4849, 0, True, "雅丹黑", "256GB"),
            ("华为Mate60 Pro", 6949, 48, "手机", 6849, 0, True, "白沙银", "512GB"),
            ("iPad Pro", 6249, 45, "平板", 6199, 0, True, "深空灰", "128GB"),
            ("iPad Pro", 7449, 33, "平板", 7399, 0, True, "银色", "256GB"),
            ("小米平板6", 2149, 110, "平板", 2099, 0, True, "黑色", "128GB"),
            ("小米平板6 Pro", 2649, 85, "平板", 2599, 0, True, "金色", "256GB"),
            ("MacBook Pro 14", 14899, 28, "电脑", 14799, 0, True, "深空灰", "512GB"),
            ("AirPods Pro", 1849, 190, "配件", 1799, 0, True, None, None)
        ]
    }
    
    print("=" * 60)
    print("正在初始化多平台数据库...")
    print("=" * 60)
    
    for platform_id, data in platform_data.items():
        db = PlatformDatabase(platform_id)
        db.init_platform_db(data)
        db.close()
    
    print("=" * 60)
    print("所有平台数据库初始化完成！")
    print("=" * 60)


if __name__ == "__main__":
    init_all_platforms()
