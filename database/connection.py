"""Подключение к БД (PostgreSQL через asyncpg) и инициализация схемы.

Оптимизации для Railway:
- max_size=20 (больше соединений под нагрузку)
- max_inactive_time=300 (не закрываем соединения 5 мин)
- command_timeout=10 (быстрее отваливаемся при зависании)
- sslmode=prefer (не require — Railway internal network доверенная)
- statement_cache_size=5000 (кэшируем prepared statements)

Модель доступа:
    db()             — асинхронный контекстный менеджер для работы с БД.
    get_single_db()  — НОВОЕ соединение из пула для транзакций.
    close_db_pool()  — закрывает пул (graceful shutdown).
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import asyncpg

from config import DATABASE_URL

log = logging.getLogger("iskra.db")

_pool: Optional[asyncpg.Pool] = None
_schema_ready = False


def _build_dsn() -> str:
    """Формирует DSN с оптимальными параметрами для Railway."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан!")

    dsn = DATABASE_URL

    # Для Railway internal connections используем prefer вместо require
    # Это убирает SSL-handshake (~50-100ms на соединение)
    if "sslmode=" not in dsn:
        sep = "&" if "?" in dsn else "?"
        # Railway internal network — доверенная, можно prefer
        dsn += f"{sep}sslmode=prefer"

    return dsn


async def _init_pool() -> asyncpg.Pool:
    """Создаёт оптимизированный пул соединений."""
    dsn = _build_dsn()
    log.info("Создаю пул соединений с PostgreSQL...")

    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=3,              # Всегда держим 3 соединения готовыми
        max_size=20,             # До 20 под пиковой нагрузкой
        max_inactive_time=300,   # Не закрываем соединения 5 минут
        command_timeout=10,        # 10 сек на запрос — хватит с запасом
        statement_cache_size=5000,  # Кэшируем prepared statements
        max_queries=50000,       # Пересоздаём соединение после 50к запросов
        server_settings={
            "jit": "off",
            "application_name": "iskra_bot",
        },
        # Кастомная инициализация каждого соединения
        init=_init_connection,
    )
    log.info("Пул создан (min=3, max=20)")
    return pool


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Инициализация каждого нового соединения в пуле."""
    # Устанавливаем timezone для консистентности
    await conn.execute("SET TIMEZONE TO 'UTC'")


async def _get_pool() -> asyncpg.Pool:
    """Возвращает существующий пул или создаёт новый."""
    global _pool
    if _pool is None:
        _pool = await _init_pool()
    return _pool


@asynccontextmanager
async def db() -> AsyncGenerator[asyncpg.Connection, None]:
    """Контекстный менеджер для работы с БД из пула."""
    global _schema_ready

    pool = await _get_pool()

    if not _schema_ready:
        async with pool.acquire() as init_conn:
            try:
                await init_schema(init_conn)
                _schema_ready = True
                log.info("Схема БД инициализирована")
            except Exception as e:
                log.error("Ошибка инициализации схемы: %s", e)
                raise

    async with pool.acquire() as conn:
        yield conn


async def get_single_db() -> asyncpg.Connection:
    """Свежее соединение из пула для транзакций."""
    global _schema_ready
    pool = await _get_pool()
    if not _schema_ready:
        async with pool.acquire() as init_conn:
            await init_schema(init_conn)
            _schema_ready = True
    return await pool.acquire()


async def close_db_pool() -> None:
    """Закрывает пул соединений."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("Пул соединений закрыт")


# ═══════════════════════════════════════════════════════════════════════════════
# INLINE СХЕМА
# ═══════════════════════════════════════════════════════════════════════════════

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
CREATE INDEX IF NOT EXISTS idx_anon_sessions_active ON anon_sessions(ended_at);
CREATE INDEX IF NOT EXISTS idx_relationships_pair  ON relationships(user1_id, user2_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status      ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_user_badges_tg      ON user_badges(tg_id);
CREATE INDEX IF NOT EXISTS idx_users_age           ON users(active, is_banned, age);
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
    "photos": [
        ("id", "SERIAL", None),
        ("tg_id", "BIGINT", "0"),
        ("photo_id", "TEXT", "''"),
        ("position", "INTEGER", "0"),
    ],
    "likes": [
        ("id", "SERIAL", None),
        ("from_id", "BIGINT", "0"),
        ("to_id", "BIGINT", "0"),
        ("is_like", "INTEGER", "1"),
        ("message", "TEXT", "NULL"),
        ("created_at", "INTEGER", "0"),
    ],
    "matches": [
        ("id", "SERIAL", None),
        ("a_id", "BIGINT", "0"),
        ("b_id", "BIGINT", "0"),
        ("created_at", "INTEGER", "0"),
    ],
    "shown_profiles": [
        ("from_id", "BIGINT", "0"),
        ("to_id", "BIGINT", "0"),
        ("shown_at", "INTEGER", "0"),
    ],
    "reports": [
        ("id", "SERIAL", None),
        ("from_id", "BIGINT", "0"),
        ("to_id", "BIGINT", "0"),
        ("created_at", "INTEGER", "0"),
    ],
    "anon_queue": [
        ("tg_id", "BIGINT", "0"),
        ("queued_at", "INTEGER", "0"),
    ],
    "anon_sessions": [
        ("id", "SERIAL", None),
        ("a_id", "BIGINT", "0"),
        ("b_id", "BIGINT", "0"),
        ("a_reveal", "INTEGER", "0"),
        ("b_reveal", "INTEGER", "0"),
        ("started_at", "INTEGER", "0"),
        ("ended_at", "INTEGER", "NULL"),
    ],
    "relationships": [
        ("id", "SERIAL", None),
        ("user1_id", "BIGINT", "0"),
        ("user2_id", "BIGINT", "0"),
        ("points", "INTEGER", "0"),
        ("level", "INTEGER", "0"),
        ("created_at", "INTEGER", "0"),
    ],
    "tickets": [
        ("id", "SERIAL", None),
        ("tg_id", "BIGINT", "0"),
        ("category", "TEXT", "'other'"),
        ("text", "TEXT", "''"),
        ("photo_id", "TEXT", "NULL"),
        ("reply", "TEXT", "NULL"),
        ("status", "TEXT", "'open'"),
        ("created_at", "INTEGER", "0"),
    ],
    "user_badges": [
        ("tg_id", "BIGINT", "0"),
        ("badge_id", "TEXT", "''"),
        ("awarded_at", "INTEGER", "0"),
    ],
}


async def _ensure_columns(conn: asyncpg.Connection) -> None:
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
            except Exception as e:
                log.warning("Колонка %s.%s: %s", table, col_name, e)


async def _migrate_types(conn: asyncpg.Connection) -> None:
    type_migrations = [
        ("users", "created_at", "INTEGER", "0"),
        ("users", "last_active", "INTEGER", "0"),
        ("likes", "created_at", "INTEGER", "0"),
        ("matches", "created_at", "INTEGER", "0"),
        ("shown_profiles", "shown_at", "INTEGER", "0"),
        ("reports", "created_at", "INTEGER", "0"),
        ("anon_queue", "queued_at", "INTEGER", "0"),
        ("anon_sessions", "started_at", "INTEGER", "0"),
        ("anon_sessions", "ended_at", "INTEGER", "NULL"),
        ("relationships", "created_at", "INTEGER", "0"),
        ("tickets", "created_at", "INTEGER", "0"),
    ]

    for table, col_name, new_type, default_val in type_migrations:
        try:
            row = await conn.fetchrow(
                """SELECT data_type FROM information_schema.columns 
                WHERE table_name = $1 AND column_name = $2""",
                table, col_name
            )
            if row and row["data_type"] in ("timestamp without time zone", "timestamp with time zone", "timestamp"):
                await conn.execute(
                    f"ALTER TABLE {table} ALTER COLUMN {col_name} DROP DEFAULT"
                )
                await conn.execute(
                    f"ALTER TABLE {table} ALTER COLUMN {col_name} TYPE {new_type} \
                    USING EXTRACT(EPOCH FROM {col_name})::INTEGER"
                )
                if default_val != "NULL":
                    await conn.execute(
                        f"ALTER TABLE {table} ALTER COLUMN {col_name} SET DEFAULT {default_val}"
                    )
                else:
                    await conn.execute(
                        f"ALTER TABLE {table} ALTER COLUMN {col_name} SET DEFAULT NULL"
                    )
                log.info("Мигрирован %s.%s -> %s", table, col_name, new_type)
        except Exception as e:
            log.warning("Миграция %s.%s: %s", table, col_name, e)


async def _clear_statement_cache(conn: asyncpg.Connection) -> None:
    try:
        await conn.execute("DEALLOCATE ALL")
    except Exception:
        pass


async def init_schema(conn: asyncpg.Connection) -> None:
    log.info("Создаю таблицы...")
    await conn.execute(SCHEMA_SQL)
    await _ensure_columns(conn)
    await _migrate_types(conn)
    await _clear_statement_cache(conn)
    await conn.execute(INDEX_SQL)
    log.info("Таблицы созданы")
