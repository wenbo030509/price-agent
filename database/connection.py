import sqlite3
import threading


class DatabaseConnection:
    """数据库连接管理类"""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._local = threading.local()

    def connect(self):
        """建立数据库连接（每个线程独立）"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        return self._local.conn

    def get_cursor(self):
        """获取数据库游标"""
        conn = self.connect()
        return conn.cursor()

    def commit(self):
        """提交事务"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.commit()

    def close(self):
        """关闭数据库连接"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    @property
    def connection(self):
        """获取数据库连接"""
        return self.connect()
