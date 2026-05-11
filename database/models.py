from .connection import DatabaseConnection
from typing import List, Dict, Optional
import datetime


def init_mock_db(db: DatabaseConnection):
    """
    初始化SQLite数据库，创建表结构并插入Mock商品数据
    :param db: DatabaseConnection实例
    """
    cursor = db.get_cursor()

    # 创建商品表
    cursor.execute('''
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL,
            category TEXT NOT NULL
        )
    ''')

    # 创建会话历史表
    cursor.execute('''
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 创建会话消息表
    cursor.execute('''
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions (session_id)
        )
    ''')

    # 插入Mock数据
    mock_products = [
        ("iPhone 15", 5999, 100, "手机"),
        ("小米14", 3999, 150, "手机"),
        ("华为Mate60", 4999, 80, "手机"),
        ("iPad Pro", 6299, 50, "平板"),
        ("小米平板6", 2199, 120, "平板")
    ]

    cursor.executemany(
        "INSERT INTO products (product_name, price, stock, category) VALUES (?, ?, ?, ?)",
        mock_products
    )

    db.commit()
    return db


def add_product(db: DatabaseConnection, product_name: str, price: float, stock: int, category: str) -> Dict:
    """
    添加新商品
    :param db: DatabaseConnection实例
    :param product_name: 商品名称
    :param price: 价格
    :param stock: 库存
    :param category: 品类
    :return: 新增的商品信息
    """
    cursor = db.get_cursor()
    cursor.execute(
        "INSERT INTO products (product_name, price, stock, category) VALUES (?, ?, ?, ?)",
        (product_name, price, stock, category)
    )
    product_id = cursor.lastrowid
    db.commit()

    return {
        "id": product_id,
        "product_name": product_name,
        "price": price,
        "stock": stock,
        "category": category
    }


def get_all_products(db: DatabaseConnection) -> List[Dict]:
    """
    获取所有商品
    :param db: DatabaseConnection实例
    :return: 商品列表
    """
    cursor = db.get_cursor()
    cursor.execute("SELECT id, product_name, price, stock, category FROM products ORDER BY id")
    results = cursor.fetchall()
    return [
        {
            "id": row[0],
            "product_name": row[1],
            "price": row[2],
            "stock": row[3],
            "category": row[4]
        }
        for row in results
    ]


def create_session(db: DatabaseConnection, session_id: str) -> Dict:
    """
    创建新会话
    :param db: DatabaseConnection实例
    :param session_id: 会话ID
    :return: 会话信息
    """
    cursor = db.get_cursor()
    cursor.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    db.commit()
    return {
        "session_id": session_id,
        "created_at": datetime.datetime.now().isoformat()
    }


def get_all_sessions(db: DatabaseConnection) -> List[Dict]:
    """
    获取所有会话
    :param db: DatabaseConnection实例
    :return: 会话列表（含第一条用户消息作为标题）
    """
    cursor = db.get_cursor()
    cursor.execute("""
        SELECT s.session_id, s.created_at,
               (SELECT m.content FROM messages m
                WHERE m.session_id = s.session_id AND m.role = 'user'
                ORDER BY m.timestamp ASC LIMIT 1) as title
        FROM sessions s
        ORDER BY s.created_at DESC
    """)
    results = cursor.fetchall()
    return [
        {
            "session_id": row[0],
            "created_at": row[1],
            "title": row[2] or "新会话"
        }
        for row in results
    ]


def add_message(db: DatabaseConnection, session_id: str, role: str, content: str) -> Dict:
    """
    添加消息到会话
    :param db: DatabaseConnection实例
    :param session_id: 会话ID
    :param role: 角色（user/assistant）
    :param content: 消息内容
    :return: 消息信息
    """
    cursor = db.get_cursor()
    cursor.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content)
    )
    message_id = cursor.lastrowid
    db.commit()
    return {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "timestamp": datetime.datetime.now().isoformat()
    }


def get_session_messages(db: DatabaseConnection, session_id: str) -> List[Dict]:
    """
    获取会话的所有消息
    :param db: DatabaseConnection实例
    :param session_id: 会话ID
    :return: 消息列表
    """
    cursor = db.get_cursor()
    cursor.execute(
        "SELECT id, role, content, timestamp FROM messages WHERE session_id = ? ORDER BY timestamp",
        (session_id,)
    )
    results = cursor.fetchall()
    return [
        {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "timestamp": row[3]
        }
        for row in results
    ]


def delete_session(db: DatabaseConnection, session_id: str) -> bool:
    """
    删除会话
    :param db: DatabaseConnection实例
    :param session_id: 会话ID
    :return: 是否成功
    """
    cursor = db.get_cursor()
    cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    db.commit()
    return True
