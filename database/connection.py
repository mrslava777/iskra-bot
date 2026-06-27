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

# Индексы создаются ПОСЛЕ миграции (могут ссылаться на колонки, которые
# добавляются миграцией со старой схемы, напр. anon_sessions.ended_at).
INDEXES = """
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


async def _table_exists(conn: aiosqlite.Connection, name: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return await cur.fetchone() is not None


async def _columns(conn: aiosqlite.Connection, table: str) -> set:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in await cur.fetchall()}


async def _add_column(conn, table: str, column: str, decl: str) -> None:
    """Идемпотентно добавляет колонку (ALTER ... ADD COLUMN), если её нет."""
    if column not in await _columns(conn, table):
        try:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        except Exception:
            pass


async def _migrate(conn: aiosqlite.Connection) -> None:
    """Безопасная идемпотентная миграция со старой схемы прод-бота.

    Старая (монолитная) архитектура использовала другие имена таблиц
    (user_photos, support_tickets) и часть других колонок (anon_queue.created_at,
    anon_sessions.ended). Здесь мы аккуратно подтягиваем существующую базу под
    новую схему, НЕ удаляя старые таблицы (остаются как резервная копия).
    """
    # 1. Недостающие колонки в users (для очень старых баз без новой схемы).
    await _add_column(conn, "users", "min_age", "INTEGER DEFAULT 18")
    await _add_column(conn, "users", "max_age", "INTEGER DEFAULT 99")
    await _add_column(conn, "users", "max_compat", "INTEGER DEFAULT 0")

    # 2. anon_queue: старое поле created_at -> новое queued_at.
    if await _table_exists(conn, "anon_queue"):
        cols = await _columns(conn, "anon_queue")
        if "queued_at" not in cols:
            await _add_column(conn, "anon_queue", "queued_at", "INTEGER DEFAULT 0")
            if "created_at" in cols:
                await conn.execute(
                    "UPDATE anon_queue SET queued_at = COALESCE(created_at, 0) "
                    "WHERE queued_at IS NULL OR queued_at = 0"
                )

    # 3. anon_sessions: старые ended/created_at -> started_at/ended_at.
    if await _table_exists(conn, "anon_sessions"):
        cols = await _columns(conn, "anon_sessions")
        await _add_column(conn, "anon_sessions", "started_at", "INTEGER DEFAULT 0")
        await _add_column(conn, "anon_sessions", "ended_at", "INTEGER")
        if "created_at" in cols:
            await conn.execute(
                "UPDATE anon_sessions SET started_at = COALESCE(created_at, 0) "
                "WHERE started_at IS NULL OR started_at = 0"
            )
        if "ended" in cols:
            # Завершённые в старой схеме сессии помечаем ended_at, чтобы новый
            # код (ended_at IS NULL = активная) не воскресил их.
            await conn.execute(
                "UPDATE anon_sessions SET ended_at = COALESCE(ended_at, "
                "CASE WHEN started_at > 0 THEN started_at ELSE strftime('%s','now') END) "
                "WHERE ended = 1 AND ended_at IS NULL"
            )

    # 4. Перенос фотогалереи: user_photos (старое имя) -> photos (новое).
    if await _table_exists(conn, "user_photos"):
        cur = await conn.execute("SELECT COUNT(*) FROM photos")
        if (await cur.fetchone())[0] == 0:
            await conn.execute(
                "INSERT OR IGNORE INTO photos (tg_id, photo_id, position) "
                "SELECT tg_id, photo_id, position FROM user_photos"
            )

    # 5. Перенос тикетов: support_tickets (старое) -> tickets (новое).
    if await _table_exists(conn, "support_tickets"):
        cur = await conn.execute("SELECT COUNT(*) FROM tickets")
        if (await cur.fetchone())[0] == 0:
            old_cols = await _columns(conn, "support_tickets")
            text_col = "message" if "message" in old_cols else "text"
            reply_col = "admin_reply" if "admin_reply" in old_cols else "reply"
            await conn.execute(
                f"INSERT OR IGNORE INTO tickets "
                f"(id, tg_id, category, text, photo_id, reply, status, created_at) "
                f"SELECT id, tg_id, category, {text_col}, photo_id, {reply_col}, "
                f"status, created_at FROM support_tickets"
            )

    await conn.commit()


async def init_schema(conn: aiosqlite.Connection) -> None:
    """Создаёт все таблицы и индексы (идемпотентно) + миграция со старой схемы."""
    await conn.executescript(SCHEMA)
    await conn.commit()
    # Миграция добавляет недостающие колонки (ended_at и т.п.) ДО создания индексов.
    await _migrate(conn)
    await conn.executescript(INDEXES)
    await conn.commit()
