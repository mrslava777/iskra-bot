"""Подключение к БД (SQLite через aiosqlite) и инициализация схемы.

Модель доступа:
    get_db()         — общее долгоживущее соединение для ЧТЕНИЯ
                       (row_factory = aiosqlite.Row, поддерживает row["col"] и dict(row)).
    get_single_db()  — НОВОЕ соединение на каждую ЗАПИСЬ; вызывающий сам
                       делает .execute()/.commit()/.close().
    close_db_pool()  — закрывает общее соединение (graceful shutdown).

Схема создаётся один раз в init_schema() при первом get_db().
"""
import os
from typing import Optional

import aiosqlite

from config import DB_PATH

_db: Optional[aiosqlite.Connection] = None
_schema_ready = False


def _ensure_parent() -> None:
    parent = os.path.dirname(os.path.abspath(DB_PATH))
    if parent:
        os.makedirs(parent, exist_ok=True)


async def _configure(conn: aiosqlite.Connection) -> None:
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    await conn.execute("PRAGMA synchronous=NORMAL;")
    await conn.execute("PRAGMA busy_timeout=5000;")
    await conn.execute("PRAGMA cache_size=-8000;")


async def get_db() -> aiosqlite.Connection:
    """Общее соединение для чтения. Создаёт схему при первом вызове."""
    global _db, _schema_ready
    if _db is None:
        _ensure_parent()
        _db = await aiosqlite.connect(DB_PATH)
        await _configure(_db)
    if not _schema_ready:
        await init_schema(_db)
        _schema_ready = True
    return _db


async def get_single_db() -> aiosqlite.Connection:
    """Свежее соединение для записи. Вызывающий обязан закрыть его сам."""
    global _schema_ready
    _ensure_parent()
    # Гарантируем, что схема существует (например, если запись идёт раньше чтения).
    if not _schema_ready:
        await get_db()
    conn = await aiosqlite.connect(DB_PATH)
    await _configure(conn)
    return conn


async def close_db_pool() -> None:
    """Закрывает общее соединение (graceful shutdown)."""
    global _db
    if _db is not None:
        try:
            await _db.commit()
        finally:
            await _db.close()
            _db = None


SCHEMA = """
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

-- Индексы под горячие пути
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
"""


async def init_schema(conn: aiosqlite.Connection) -> None:
    """Создаёт все таблицы и индексы (идемпотентно)."""
    await conn.executescript(SCHEMA)
    await conn.commit()
