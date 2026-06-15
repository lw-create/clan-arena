import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("CLAN_ARENA_DB", "clan_arena.db")


class CursorContextManager:
    """让 sqlite3.Cursor 支持 with 语句，兼容 pymysql 的用法，同时代理所有 cursor 方法"""
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self._cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass  # sqlite3 cursor 不需要显式关闭

    def __getattr__(self, name):
        """代理所有未定义的属性/方法到底层 cursor"""
        return getattr(self._cursor, name)


def dict_factory(cursor, row):
    """让 SQLite 返回字典格式结果"""
    fields = [column[0] for column in cursor.description]
    return dict(zip(fields, row))


class SqliteConnectionWrapper:
    """包装 sqlite3.Connection，让 cursor() 返回上下文管理器"""
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return CursorContextManager(self._conn.cursor())

    def execute(self, sql, params=None):
        if params:
            return self._conn.execute(sql, params)
        return self._conn.execute(sql)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys = ON")
    return SqliteConnectionWrapper(conn)


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        # users 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                plain_password TEXT DEFAULT '',
                role TEXT DEFAULT 'player' CHECK(role IN ('player', 'admin', 'monitor')),
                is_super_admin INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'frozen', 'disabled')),
                must_change_pwd INTEGER DEFAULT 1,
                cancel_count_round_id INTEGER DEFAULT NULL,
                cancel_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # clans 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                contact TEXT DEFAULT '',
                score INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # user_clan 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_clan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                clan_id INTEGER NOT NULL,
                bound_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, clan_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (clan_id) REFERENCES clans(id) ON DELETE CASCADE
            )
        """)
        # matches 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clan_a_id INTEGER NOT NULL,
                clan_b_id INTEGER NOT NULL,
                winner_id INTEGER,
                loser_id INTEGER,
                score_before_a INTEGER,
                score_before_b INTEGER,
                is_registered INTEGER DEFAULT 1,
                remark TEXT,
                config_remark TEXT DEFAULT NULL,
                created_by INTEGER,
                confirmed_by INTEGER DEFAULT NULL,
                matched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (clan_a_id) REFERENCES clans(id),
                FOREIGN KEY (clan_b_id) REFERENCES clans(id),
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        """)
        # notifications 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # operation_logs 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id INTEGER,
                detail TEXT,
                reason TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES users(id)
            )
        """)
        # unknown_clans 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS unknown_clans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                tags TEXT DEFAULT '',
                encounter_count INTEGER DEFAULT 1,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # rounds 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_no INTEGER NOT NULL,
                status TEXT DEFAULT 'open' CHECK(status IN ('open', 'closed')),
                opened_by INTEGER,
                closed_by INTEGER DEFAULT NULL,
                opened_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed_at DATETIME DEFAULT NULL,
                match_start_time DATETIME DEFAULT NULL,
                match_end_time DATETIME DEFAULT NULL,
                next_round_time DATETIME DEFAULT NULL,
                config_required INTEGER DEFAULT 0,
                maintenance INTEGER DEFAULT 0,
                FOREIGN KEY (opened_by) REFERENCES users(id)
            )
        """)
        # round_registrations 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS round_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                clan_id INTEGER NOT NULL,
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(round_id, user_id, clan_id),
                FOREIGN KEY (round_id) REFERENCES rounds(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (clan_id) REFERENCES clans(id) ON DELETE CASCADE
            )
        """)
        # match_queue 表（匹配队列）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS match_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                clan_id INTEGER NOT NULL,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (clan_id) REFERENCES clans(id)
            )
        """)
        # score_guide 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS score_guide (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully")
