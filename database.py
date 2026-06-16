import os
import ssl
from contextlib import contextmanager

import pymysql


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def _config():
    db_host = _env("DB_HOST", "localhost")
    cfg = {
        "host": db_host,
        "port": int(_env("DB_PORT", "4000" if db_host else "3306")),
        "user": _env("DB_USER", "root"),
        "password": _env("DB_PASSWORD", ""),
        "database": _env("DB_NAME", "clan_arena"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
        "connect_timeout": 10,
    }
    if _env("DB_SSL").lower() in {"1", "true", "yes"} or "tidbcloud.com" in cfg["host"]:
        cfg["ssl"] = ssl.create_default_context()
    return cfg


class CompatCursor:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cur.close()

    def __getattr__(self, name):
        return getattr(self.cur, name)

    def execute(self, sql, args=None):
        if isinstance(sql, str):
            sql = sql.replace("?", "%s")
        return self.cur.execute(sql, args)

    def executemany(self, sql, args=None):
        if isinstance(sql, str):
            sql = sql.replace("?", "%s")
        return self.cur.executemany(sql, args)


class CompatConn:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def cursor(self, *args, **kwargs):
        return CompatCursor(self.conn.cursor(*args, **kwargs))


def get_connection():
    return CompatConn(pymysql.connect(**_config()))


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


TABLES = [
    """CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        plain_password VARCHAR(100) DEFAULT '',
        role ENUM('player','admin','monitor') DEFAULT 'player',
        is_super_admin BOOLEAN DEFAULT FALSE,
        status ENUM('active','frozen','disabled') DEFAULT 'active',
        must_change_pwd BOOLEAN DEFAULT TRUE,
        cancel_count_round_id INT DEFAULT NULL,
        cancel_count INT DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS clans (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        code VARCHAR(50) UNIQUE NOT NULL,
        contact VARCHAR(200) DEFAULT '',
        score INT DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS user_clan (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        clan_id INT NOT NULL,
        bound_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_user_clan (user_id, clan_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS matches (
        id INT AUTO_INCREMENT PRIMARY KEY,
        clan_a_id INT NOT NULL,
        clan_b_id INT NOT NULL,
        winner_id INT,
        loser_id INT,
        score_before_a INT,
        score_before_b INT,
        is_registered BOOLEAN DEFAULT TRUE,
        remark TEXT,
        config_remark VARCHAR(500) DEFAULT NULL,
        created_by INT,
        confirmed_by INT DEFAULT NULL,
        matched_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS notifications (
        id INT AUTO_INCREMENT PRIMARY KEY,
        content TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS operation_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        admin_id INT NOT NULL,
        action VARCHAR(50) NOT NULL,
        target_type VARCHAR(50),
        target_id INT,
        detail TEXT,
        reason VARCHAR(200),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS unknown_clans (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        code VARCHAR(50) NOT NULL,
        tags VARCHAR(200) DEFAULT '',
        encounter_count INT DEFAULT 1,
        last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_code (code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS rounds (
        id INT AUTO_INCREMENT PRIMARY KEY,
        round_no INT NOT NULL,
        status ENUM('open','closed') DEFAULT 'open',
        opened_by INT,
        closed_by INT DEFAULT NULL,
        opened_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        closed_at DATETIME DEFAULT NULL,
        match_start_time DATETIME DEFAULT NULL,
        match_end_time DATETIME DEFAULT NULL,
        next_round_time DATETIME DEFAULT NULL,
        next_match_start_time DATETIME DEFAULT NULL,
        next_match_end_time DATETIME DEFAULT NULL,
        config_required BOOLEAN DEFAULT FALSE,
        maintenance BOOLEAN DEFAULT FALSE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS round_registrations (
        id INT AUTO_INCREMENT PRIMARY KEY,
        round_id INT NOT NULL,
        user_id INT NOT NULL,
        clan_id INT NOT NULL,
        registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_round_user_clan (round_id, user_id, clan_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS score_guide (
        id INT AUTO_INCREMENT PRIMARY KEY,
        content TEXT NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS system_settings (
        `key` VARCHAR(100) PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS clan_configs (
        clan_id INT PRIMARY KEY,
        target_total INT NOT NULL,
        updated_by INT NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS clan_config_items (
        id INT AUTO_INCREMENT PRIMARY KEY,
        clan_id INT NOT NULL,
        th_level INT NOT NULL,
        member_count INT NOT NULL,
        sort_order INT DEFAULT 0,
        UNIQUE KEY uk_clan_th_level (clan_id, th_level)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


MIGRATIONS = [
    "ALTER TABLE users MODIFY COLUMN role ENUM('player','admin','monitor') DEFAULT 'player'",
    "ALTER TABLE users ADD COLUMN is_super_admin BOOLEAN DEFAULT FALSE AFTER role",
    "ALTER TABLE users ADD COLUMN must_change_pwd BOOLEAN DEFAULT TRUE AFTER status",
    "ALTER TABLE users ADD COLUMN cancel_count_round_id INT DEFAULT NULL AFTER must_change_pwd",
    "ALTER TABLE users ADD COLUMN cancel_count INT DEFAULT 0 AFTER cancel_count_round_id",
    "ALTER TABLE matches ADD COLUMN created_by INT AFTER remark",
    "ALTER TABLE matches ADD COLUMN confirmed_by INT DEFAULT NULL AFTER created_by",
    "ALTER TABLE matches ADD COLUMN config_remark VARCHAR(500) DEFAULT NULL AFTER remark",
    "ALTER TABLE rounds ADD COLUMN match_start_time DATETIME DEFAULT NULL AFTER closed_at",
    "ALTER TABLE rounds ADD COLUMN match_end_time DATETIME DEFAULT NULL AFTER match_start_time",
    "ALTER TABLE rounds ADD COLUMN next_round_time DATETIME DEFAULT NULL AFTER match_end_time",
    "ALTER TABLE rounds ADD COLUMN next_match_start_time DATETIME DEFAULT NULL AFTER next_round_time",
    "ALTER TABLE rounds ADD COLUMN next_match_end_time DATETIME DEFAULT NULL AFTER next_match_start_time",
    "ALTER TABLE rounds ADD COLUMN config_required BOOLEAN DEFAULT FALSE AFTER next_round_time",
    "ALTER TABLE rounds ADD COLUMN maintenance BOOLEAN DEFAULT FALSE AFTER config_required",
]


def init_db():
    with get_db() as conn:
        with conn.cursor() as cursor:
            for sql in TABLES:
                cursor.execute(sql)
            for sql in MIGRATIONS:
                try:
                    cursor.execute(sql)
                except Exception:
                    pass


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully")
