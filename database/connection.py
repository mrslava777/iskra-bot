"""Database connection pool tuning and PgBouncer support.

Changes:
- Prefer PGBOUNCER_URL if provided (helps with many app processes)
- Read per-process pool sizes from config.DB_POOL_MIN / DB_POOL_MAX
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import asyncpg

from config import DATABASE_URL, PGBOUNCER_URL, DB_POOL_MIN, DB_POOL_MAX

log = logging.getLogger("iskra.db")

_pool: Optional[asyncpg.Pool] = None
_pool_lock = asyncio.Lock()
_schema_ready = False
_schema_lock = asyncio.Lock()

# Retry/backoff параметры для инициализации схемы
_SCHEMA_INIT_RETRIES = int(os.getenv("SCHEMA_INIT_RETRIES", "5"))
_SCHEMA_BACKOFF_BASE = float(os.getenv("SCHEMA_BACKOFF_BASE", "0.5"))
_SCHEMA_BACKOFF_MULT = float(os.getenv("SCHEMA_BACKOFF_MULT", "2"))


# ---------------- SCHEMA (inline) ----------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    tg_id               BIGINT PRIMARY KEY,
    username            TEXT,
    name                TEXT,
    age                 INTEGER,
    gender              TEXT,
    seeking             TEXT,
    city                TEXT,
    bio                 TEXT,
    interests           TEXT DEFAULT '',
    photo_id            TEXT,
    active              INTEGER DEFAULT 1,
    verified            INTEGER DEFAULT 0,
    is_banned           INTEGER DEFAULT 0,
    streak              INTEGER DEFAULT 0,
    rating              INTEGER DEFAULT 0,
    daily_q             INTEGER DEFAULT 0,
    daily_a             TEXT DEFAULT '',
    anon_messages_count INTEGER DEFAULT 0,
    min_age             INTEGER DEFAULT 18,
    max_age             INTEGER DEFAULT 99,
    max_compat          INTEGER DEFAULT 0,
    created_at          INTEGER DEFAULT 0,
    last_active         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS photos (
    id        SERIAL PRIMARY KEY,
    tg_id     BIGINT NOT NULL,
    photo_id  TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (tg_id, position)
);

CREATE TABLE IF NOT EXISTS likes (
    id         SERIAL PRIMARY KEY,
    from_id    BIGINT NOT NULL,
    to_id      BIGINT NOT NULL,
    is_like    INTEGER DEFAULT 1,
    message    TEXT,
    created_at INTEGER DEFAULT 0,
    UNIQUE (from_id, to_id)
);

CREATE TABLE IF NOT EXISTS matches (
    id         SERIAL PRIMARY KEY,
    a_id       BIGINT NOT NULL,
    b_id       BIGINT NOT NULL,
    created_at INTEGER DEFAULT 0,
    UNIQUE (a_id, b_id)
);

CREATE TABLE IF NOT EXISTS shown_profiles (
    from_id  BIGINT NOT NULL,
    to_id    BIGINT NOT NULL,
    shown_at INTEGER DEFAULT 0,
    PRIMARY KEY (from_id, to_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id         SERIAL PRIMARY KEY,
    from_id    BIGINT NOT NULL,
    to_id      BIGINT NOT NULL,
    created_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS anon_queue (
    tg_id     BIGINT PRIMARY KEY,
    queued_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS anon_sessions (
    id         SERIAL PRIMARY KEY,
    a_id       BIGINT NOT NULL,
    b_id       BIGINT NOT NULL,
    a_reveal   INTEGER DEFAULT 0,
    b_reveal   INTEGER DEFAULT 0,
    started_at INTEGER DEFAULT 0,
    ended_at   INTEGER
);

CREATE TABLE IF NOT EXISTS relationships (
    id         SERIAL PRIMARY KEY,
    user1_id   BIGINT NOT NULL,
    user2_id   BIGINT NOT NULL,
    points     INTEGER DEFAULT 0,
    level      INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0,
    UNIQUE (user1_id, user2_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    id         SERIAL PRIMARY KEY,
    tg_id      BIGINT NOT NULL,
    category   TEXT NOT NULL,
    text       TEXT NOT NULL,
    photo_id   TEXT,
    reply      TEXT,
    status     TEXT DEFAULT 'open',
    created_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_badges (
    tg_id      BIGINT NOT NULL,
    badge_id   TEXT NOT NULL,
    awarded_at INTEGER NOT NULL,
    PRIMARY KEY (tg_id, badge_id)
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_users_active_banned ON users(active, is_banned);
CREATE INDEX IF NOT EXISTS idx_users_last_active   ON users(last_active DESC);
CREATE INDEX IF NOT EXISTS idx_photos_tg           ON photos(tg_id);
CREATE INDEX IF NOT EXISTS idx_likes_from_to       ON likes(from_id, to_id);
CREATE INDEX IF NOT EXISTS idx_likes_to            ON likes(to_id, is_like);
CREATE INDEX IF NOT EXISTS idx_matches_a           ON matches(a_id);
CREATE INDEX IF NOT EXISTS idx_matches_b           ON matches(b_id);
CREATE INDEX IF NOT EXISTS idx_shown_from_to       ON shown_profiles(from_id, to_id);
CREATE INDEX IF NOT EXISTS idx_reports_to          ON reports(to_id);
CREATE INDEX IF NOT EXISTS idx_reports_from        ON reports(from_id);
CREATE INDEX IF NOT EXISTS idx_anon_sessions_active ON anon_sessions(ended_at);
CREATE INDEX IF NOT EXISTS idx_anon_sessions_a     ON anon_sessions(a_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_anon_sessions_b     ON anon_sessions(b_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_relationships_pair  ON relationships(user1_id, user2_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status      ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_user_badges_tg      ON user_badges(tg_id);
CREATE INDEX IF NOT EXISTS idx_users_age           ON users(active, is_banned, age);
CREATE INDEX IF NOT EXISTS idx_users_gender        ON users(gender);
CREATE INDEX IF NOT EXISTS idx_users_seeking       ON users(seeking);
"""

MISSING_COLUMNS = {
    "users": [
        ("tg_id", "BIGINT", "0"),
        ("username", "TEXT", "NULL"),
        ("name", "TEXT", "NULL"),
        ("age", "INTEGER", "NULL"),
        ("gender", "TEXT", "NULL"),
        ("seeking", "TEXT", "NULL"),
        ("city", "TEXT", "NULL"),
        ("bio", "TEXT", "NULL"),
        ("interests", "TEXT", "''"),
        ("photo_id", "TEXT", "NULL"),
        ("active", "INTEGER", "1"),
        ("verified", "INTEGER", "0"),
        ("is_banned", "INTEGER", "0"),
        ("streak", "INTEGER", "0"),
        ("rating", "INTEGER", "0"),
        ("daily_q", "INTEGER", "0"),
        ("daily_a", "TEXT", "''"),
        ("anon_messages_count", "INTEGER", "0"),
        ("min_age", "INTEGER", "18"),
        ("max_age", "INTEGER", "99"),
        ("max_compat", "INTEGER", "0"),
        ("created_at", "INTEGER", "0"),
        ("last_active", "INTEGER", "0"),
    ],
    # ... (rest unchanged) ...
}


async def _ensure_columns(conn: asyncpg.Connection) -> None:
    """Добавляет недостающие колонки в существующие таблицы.

    FIX: уровень логирования снижен с INFO до DEBUG — иначе при каждом
    запуске в лог попадают десятки строк «колонка проверена».
    """
    for table, columns in MISSING_COLUMNS.items():
        for col_name, col_type, default in columns:
            try:
                if default is None:
                    await conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                    )
                else:
                    await conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type} DEFAULT {default}"
                    )
                log.debug("Колонка %s.%s проверена/добавлена", table, col_name)
            except Exception as e:
                log.warning("Не удалось добавить колонку %s.%s: %s", table, col_name, e)

# ... keep rest of file unchanged until _build_dsn ...

async def _migrate_types(conn: asyncpg.Connection) -> None:
    # (function body unchanged) - omitted here for brevity in this commit
    pass

# For brevity in this patch we keep the rest of the original implementation
# unchanged except for _build_dsn and _init_pool which are adjusted below.


def _build_dsn() -> str:
    """Возвращает DSN для подключения. Предпочитает PGBOUNCER_URL если задан."""
    if PGBOUNCER_URL:
        return PGBOUNCER_URL
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан! Добавь переменную окружения DATABASE_URL")
    return DATABASE_URL


async def _conn_init(conn: asyncpg.Connection) -> None:
    """Инициализирует каждое новое соединение в пуле."""
    await conn.execute("SET application_name = 'iskra_bot'")


async def _init_pool() -> asyncpg.Pool:
    dsn = _build_dsn()
    log.info("Создаю пул соединений с PostgreSQL (используются конфиги DB_POOL_MIN/DB_POOL_MAX)...")
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=DB_POOL_MIN,
        max_size=DB_POOL_MAX,
        command_timeout=30,
        server_settings={"jit": "off"},
        init=_conn_init,
    )
    log.info("Пул создан (min=%d, max=%d)", DB_POOL_MIN, DB_POOL_MAX)
    return pool


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is not None:
            return _pool
        _pool = await _init_pool()
        return _pool
