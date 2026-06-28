"""Подключение к БД с поддержкой Postgres (asyncpg) и локального SQLite (aiosqlite) в качестве
fallback для локальной разработки.

Поведение:
- Если переменная окружения DATABASE_URL определена — используется asyncpg pool (Postgres).
- Иначе используется SQLite по пути DB_PATH (по умолчанию /data/iskra.db) через aiosqlite.

Цель: сделать локальную разработку и тестирование проще (не требовать Postgres), не ломая
интерфейс: db() как async context manager, get_single_db()/release_db() и close_db_pool().

Замечание: схема SQL транслируется для SQLite простыми текстовыми заменами (SERIAL ->
INTEGER PRIMARY KEY AUTOINCREMENT, EXTRACT(EPOCH FROM NOW())::INTEGER -> strftime), а
индексы с WHERE опущены для совместимости.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

# Опциональные драйверы
try:
    import asyncpg
except Exception:  # pragma: no cover - optional at import time
    asyncpg = None

try:
    import aiosqlite
except Exception:  # pragma: no cover - optional at import time
    aiosqlite = None

from config import DATABASE_URL

log = logging.getLogger("iskra.db")

# Общие состояния
_pool: Optional[object] = None  # asyncpg.Pool или заглушка для sqlite
_pool_lock = asyncio.Lock()
_schema_ready = False
_schema_lock = asyncio.Lock()

# --- SQLite specific globals ---
_sqlite_conn: Optional[aiosqlite.Connection] = None
_sqlite_db_path = os.getenv("DB_PATH", "/data/iskra.db")

# --- Postgres settings defaults ---
_PG_MIN = int(os.getenv("PG_POOL_MIN", "2"))
_PG_MAX = int(os.getenv("PG_POOL_MAX", "10"))


def _using_postgres() -> bool:
    return bool(DATABASE_URL)


def _build_dsn() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан! Добавь переменную окружения DATABASE_URL")
    return DATABASE_URL


async def _conn_init(conn) -> None:  # asyncpg.Connection
    try:
        await conn.execute("SET application_name = 'iskra_bot'")
    except Exception:
        # Best-effort for Postgres only
        pass


async def _init_pool() -> "asyncpg.Pool":
    """Создаёт пул соединений с PostgreSQL."""
    if asyncpg is None:
        raise RuntimeError("asyncpg не установлен, но DATABASE_URL задан")
    dsn = _build_dsn()
    log.info("Создаю пул соединений с PostgreSQL...")
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=_PG_MIN,
        max_size=_PG_MAX,
        command_timeout=30,
        server_settings={"jit": "off"},
        init=_conn_init,
    )
    log.info("Пул создан (min=%s, max=%s)", _PG_MIN, _PG_MAX)
    return pool


# ---------------- SQLite helpers ----------------

def _translate_schema_for_sqlite(sql: str) -> str:
    s = sql
    # Простые замены типов/выражений совместимые с SQLite
    s = s.replace("SERIAL", "INTEGER PRIMARY KEY AUTOINCREMENT")
    s = s.replace("BIGINT", "INTEGER")
    s = s.replace("TEXT", "TEXT")
    s = s.replace("EXTRACT(EPOCH FROM NOW())::INTEGER", "(strftime('%s','now'))")
    s = s.replace("DEFAULT NULL", "DEFAULT NULL")
    # Уберём выражения CREATE INDEX с WHERE (sqlite поддерживает partial indexes only in newer versions,
    # и синтаксис может отличаться). Для простоты оставим только простые выражения без WHERE.
    return s


async def _init_sqlite_conn() -> aiosqlite.Connection:
    if aiosqlite is None:
        raise RuntimeError("aiosqlite не установлен — установка локального SQLite невозможна")
    # Создаём директорию, если нужно
    db_path = _sqlite_db_path
    dirname = os.path.dirname(db_path)
    if dirname and not os.path.exists(dirname):
        try:
            os.makedirs(dirname, exist_ok=True)
        except Exception:
            pass
    log.info("Открываю SQLite базу: %s", db_path)
    conn = await aiosqlite.connect(db_path)
    # Возвращаем строки как mapping (dict-like)
    conn.row_factory = aiosqlite.Row
    # Примеры оптимизаций для SQLite
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA synchronous=NORMAL;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    await conn.commit()
    return conn


class _SQLiteConnWrapper:
    """Обёртка, обеспечивающая интерфейс похожий на asyncpg.Connection для используемых методов."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def execute(self, sql: str, *params):
        await self._conn.execute(sql, params or [])
        await self._conn.commit()

    async def fetch(self, sql: str, *params):
        cur = await self._conn.execute(sql, params or [])
        rows = await cur.fetchall()
        # convert aiosqlite.Row to dict-like mapping
        return [dict(r) for r in rows]

    async def fetchrow(self, sql: str, *params):
        cur = await self._conn.execute(sql, params or [])
        row = await cur.fetchone()
        return dict(row) if row else None

    # Transaction context manager
    def transaction(self):
        return _SqliteTransaction(self._conn)


class _SqliteTransaction:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def __aenter__(self):
        await self._conn.execute('BEGIN')
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc:
            await self._conn.execute('ROLLBACK')
        else:
            await self._conn.execute('COMMIT')


# ---------------- Public API ----------------

async def _get_pool() -> object:
    """Возвращает объект пула (asyncpg.Pool) или sqlite connection wrapper."""
    global _pool, _sqlite_conn
    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is not None:
            return _pool
        if _using_postgres():
            _pool = await _init_pool()
            return _pool
        # sqlite fallback
        _sqlite_conn = await _init_sqlite_conn()
        _pool = _SQLiteConnWrapper(_sqlite_conn)
        return _pool


async def _ensure_schema(pool_obj: object) -> None:
    """Инициализация схемы (один раз)."""
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        # For Postgres we need to acquire a real connection from the pool.
        if _using_postgres():
            async with pool_obj.acquire() as conn:
                try:
                    await init_schema(conn)
                    _schema_ready = True
                    log.info("Схема БД инициализирована")
                except Exception as e:
                    log.error("Ошибка инициализации схемы: %s", e)
                    raise
        else:
            # SQLite: pool_obj is _SQLiteConnWrapper
            try:
                # translate schema and run statements
                from textwrap import dedent

                # Import SCHEMA_SQL and INDEX_SQL from module-level definitions below
                sql = _translate_schema_for_sqlite(SCHEMA_SQL)
                # Execute statements split by semicolon
                for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                    await _sqlite_conn.execute(stmt)
                # For indexes: run only statements without WHERE
                for stmt in [s.strip() for s in INDEX_SQL.split(";") if s.strip()]:
                    if "WHERE" in stmt.upper():
                        continue
                    try:
                        await _sqlite_conn.execute(stmt)
                    except Exception:
                        # best-effort
                        log.debug("Не удалось выполнить index stmt (ignored): %s", stmt)
                await _sqlite_conn.commit()
                _schema_ready = True
                log.info("SQLite: схема БД инициализирована")
            except Exception as e:
                log.error("SQLite: ошибка инициализации схемы: %s", e)
                raise


@asynccontextmanager
async def db() -> AsyncGenerator[object, None]:
    """Контекстный менеджер для работы с БД.

    Для Postgres возвращает asyncpg.Connection, для SQLite — обёртку с методами
    execute/fetch/fetchrow.
    """
    pool = await _get_pool()
    await _ensure_schema(pool)
    if _using_postgres():
        async with pool.acquire() as conn:
            yield conn
    else:
        # For sqlite yield wrapper directly
        yield pool


async def get_single_db() -> object:
    """Возвращает отдельное соединение для транзакций.

    Для Postgres — pool.acquire(); для SQLite — возвращаем тот же wrapper (single conn).
    """
    pool = await _get_pool()
    await _ensure_schema(pool)
    if _using_postgres():
        return await pool.acquire()
    return pool


async def release_db(conn: object) -> None:
    """Возвращает соединение в пул (noop для sqlite wrapper)."""
    if _using_postgres():
        pool = await _get_pool()
        await pool.release(conn)
    else:
        # nothing to do for sqlite single connection wrapper
        return


async def close_db_pool() -> None:
    """Закрывает пул/соединение graceful."""
    global _pool, _sqlite_conn, _schema_ready
    if _pool is None:
        return
    if _using_postgres() and asyncpg is not None:
        await _pool.close()
        _pool = None
        _schema_ready = False
        log.info("Пул соединений с PostgreSQL закрыт")
    else:
        try:
            await _sqlite_conn.close()
        except Exception:
            pass
        _sqlite_conn = None
        _pool = None
        _schema_ready = False
        log.info("SQLite соединение закрыто")


# ---------------- SCHEMA (original) ----------------
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
