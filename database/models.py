"""
database/models.py
商品数据统一由 platforms.PlatformDatabase 管理，主 DB 只负责会话管理。
"""
from .connection import DatabaseConnection
from typing import List, Dict, Optional
import datetime


def init_mock_db(db: DatabaseConnection):
    """
    初始化SQLite数据库，创建会话表和消息表。
    商品数据不在主 DB 存储，由 platforms.PlatformDatabase 统一管理。
    """
    cursor = db.get_cursor()

    # 创建会话历史表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 创建会话消息表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions (session_id)
        )
    ''')

    db.commit()
    return db


def create_session(db: DatabaseConnection, session_id: str) -> Dict:
    cursor = db.get_cursor()
    cursor.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    db.commit()
    return {
        "session_id": session_id,
        "created_at": datetime.datetime.now().isoformat()
    }


def get_all_sessions(db: DatabaseConnection) -> List[Dict]:
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
    cursor = db.get_cursor()
    cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    db.commit()
    return True
