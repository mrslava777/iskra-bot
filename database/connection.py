"""Подключение к БД (SQLite через aiosqlite) и инициализация схемы.

Модель доступа:
    db()             — асинхронный контекстный менеджер для работы с БД.
    get_single_db()  — НОВОЕ соединение для транзакций.
                       Вызывающий обязан вернуть через await release_db(conn).
    close_db_pool()  — закрывает соединение (graceful shutdown).

Схема создаётся один раз при первом вызове db().
"""
import asyncio
import logging
import os
import time as _time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import aiosqlite

from config import DB_PATH

log = logging.getLogger("iskra.db")

_conn: Optional[aiosqlite.Connection] = None
_conn_lock = asyncio.Lock()
_schema_ready = False
_schema_lock = asyncio.Lock()


# ---------------- SCHEMA (inline) ----------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    tg_id               INTEGER PRIMARY KEY,
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
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id     INTEGER NOT NULL,
    photo_id  TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (tg_id, position)
);

CREATE TABLE IF NOT EXISTS likes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    is_like    INTEGER DEFAULT 1,
    message    TEXT,
    created_at INTEGER DEFAULT 0,
    UNIQUE (from_id, to_id)
);

CREATE TABLE IF NOT EXISTS matches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id       INTEGER NOT NULL,
    b_id       INTEGER NOT NULL,
    created_at INTEGER DEFAULT 0,
    UNIQUE (a_id, b_id)
);

CREATE TABLE IF NOT EXISTS shown_profiles (
    from_id  INTEGER NOT NULL,
    to_id    INTEGER NOT NULL,
    shown_at INTEGER DEFAULT 0,
    PRIMARY KEY (from_id, to_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    created_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS anon_queue (
    tg_id     INTEGER PRIMARY KEY,
    queued_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS anon_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id       INTEGER NOT NULL,
    b_id       INTEGER NOT NULL,
    a_reveal   INTEGER DEFAULT 0,
    b_reveal   INTEGER DEFAULT 0,
    started_at INTEGER DEFAULT 0,
    ended_at   INTEGER
);

CREATE TABLE IF NOT EXISTS relationships (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user1_id   INTEGER NOT NULL,
    user2_id   INTEGER NOT NULL,
    points     INTEGER DEFAULT 0,
    level      INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0,
    UNIQUE (user1_id, user2_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id      INTEGER NOT NULL,
    category   TEXT NOT NULL,
    text       TEXT NOT NULL,
    photo_id   TEXT,
    reply      TEXT,
    status     TEXT DEFAULT 'open',
    created_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_badges (
    tg_id      INTEGER NOT NULL,
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
CREATE INDEX IF NOT EXISTS idx_relationships_pair  ON relationships(user1_id, user2_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status      ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_user_badges_tg      ON user_badges(tg_id);
CREATE INDEX IF NOT EXISTS idx_users_age           ON users(active, is_banned, age);
CREATE INDEX IF NOT EXISTS idx_users_gender        ON users(gender);
CREATE INDEX IF NOT EXISTS idx_users_seeking       ON users(seeking);
"""


async def init_schema(conn: aiosqlite.Connection) -> None:
    """Создаёт все таблицы и индексы (идемпотентно)."""
    log.info("Инициализация схемы БД...")
    await conn.executescript(SCHEMA_SQL)
    await conn.executescript(INDEX_SQL)
    await conn.commit()
    log.info("Схема БД готова")


async def _ensure_schema() -> None:
    """Гарантирует инициализацию схемы ровно один раз."""
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        conn = await _get_conn()
        await init_schema(conn)
        _schema_ready = True
        log.info("Схема БД инициализирована")


@asynccontextmanager
async def db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Контекстный менеджер для работы с БД.

    Берёт соединение, выполняет запросы, автоматически коммитит.
    При первом использовании инициализирует схему.
    """
    await _ensure_schema()
    conn = await _get_conn()
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise


async def get_single_db() -> aiosqlite.Connection:
    """Возвращает текущее соединение (для совместимости)."""
    await _ensure_schema()
    return await _get_conn()


async def release_db(conn: aiosqlite.Connection) -> None:
    """Ничего не делает — соединение shared (для совместимости)."""
    pass


async def close_db_pool() -> None:
    """Закрывает соединение с SQLite."""
    global _conn, _schema_ready
    if _conn is not None:
        await _conn.close()
        _conn = None
        _schema_ready = False
        log.info("Соединение с SQLite закрыто")


async def wait_until_db_ready(timeout: float = 60.0) -> None:
    """Вспомогательная утилита для блокировки старта приложения до прогрева БД."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        try:
            await _ensure_schema()
            return
        except Exception as e:
            if asyncio.get_event_loop().time() > deadline:
                log.exception("wait_until_db_ready: timeout waiting for DB ready: %s", e)
                raise
            await asyncio.sleep(0.5)


async def _get_conn() -> aiosqlite.Connection:
    """Возвращает (или создаёт) единственное соединение с SQLite."""
    global _conn
    if _conn is not None:
        return _conn
    async with _conn_lock:
        if _conn is not None:
            return _conn
        _conn = await aiosqlite.connect(DB_PATH)
        _conn.row_factory = aiosqlite.Row
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA synchronous=NORMAL")
        await _conn.execute("PRAGMA foreign_keys=ON")
        log.info("Соединение с SQLite создано: %s", DB_PATH)
        return _conn


async def ping_db() -> bool:
    """Проверяет живость соединения с БД."""
    try:
        conn = await _get_conn()
        await conn.execute("SELECT 1")
        return True
    except Exception as e:
        log.warning("DB ping failed: %s", e)
        return False
