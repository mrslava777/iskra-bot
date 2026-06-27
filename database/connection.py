"""Подключение к БД (PostgreSQL через asyncpg) и инициализация схемы.

Модель доступа:
    get_db()         — общее долгоживущее соединение для ЧТЕНИЯ
                       (возвращает asyncpg.Connection).
    get_single_db()  — НОВОЕ соединение на каждую ЗАПИСЬ; вызывающий сам
                       делает .execute()/.commit()/.close().
    close_db_pool()  — закрывает пул соединений (graceful shutdown).

Схема создаётся один раз в init_schema() при первом get_db().
"""
import os
from typing import Optional

import asyncpg

from config import DATABASE_URL

_pool: Optional[asyncpg.Pool] = None
_schema_ready = False


async def _get_pool() -> asyncpg.Pool:
    """Возвращает пул соединений (создаёт при первом вызове)."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=60,
        )
    return _pool


async def get_db() -> asyncpg.Connection:
    """Общее соединение для чтения. Создаёт схему при первом вызове."""
    global _schema_ready
    pool = await _get_pool()
    # Получаем соединение из пула
    conn = await pool.acquire()
    if not _schema_ready:
        await init_schema(conn)
        _schema_ready = True
    return conn


async def get_single_db() -> asyncpg.Connection:
    """Свежее соединение для записи. Вызывающий обязан закрыть его сам."""
    global _schema_ready
    if not _schema_ready:
        # Гарантируем, что схема существует
        await get_db()
    conn = await asyncpg.connect(dsn=DATABASE_URL)
    return conn


async def close_db_pool() -> None:
    """Закрывает пул соединений (graceful shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_schema(conn: asyncpg.Connection) -> None:
    """Создаёт все таблицы и индексы (идемпотентно) + миграция со старой схемы."""
    # Читаем schema.sql
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            sql = f.read()
        await conn.execute(sql)
    else:
        # Fallback: выполняем inline схему
        await conn.execute(SCHEMA_SQL)
    # Миграция
    await _migrate(conn)


async def _table_exists(conn: asyncpg.Connection, name: str) -> bool:
    row = await conn.fetchval(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = $1
        """,
        name,
    )
    return row is not None


async def _columns(conn: asyncpg.Connection, table: str) -> set:
    rows = await conn.fetch(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        """,
        table,
    )
    return {r["column_name"] for r in rows}


async def _add_column(conn, table: str, column: str, decl: str) -> None:
    """Идемпотентно добавляет колонку, если её нет."""
    if column not in await _columns(conn, table):
        try:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {decl}")
        except Exception:
            pass


async def _migrate(conn: asyncpg.Connection) -> None:
    """Безопасная идемпотентная миграция со старой схемы."""
    # 1. Недостающие колонки в users
    await _add_column(conn, "users", "min_age", "INTEGER DEFAULT 18")
    await _add_column(conn, "users", "max_age", "INTEGER DEFAULT 99")
    await _add_column(conn, "users", "max_compat", "INTEGER DEFAULT 0")

    # 2. anon_queue: старое поле created_at -> новое queued_at
    if await _table_exists(conn, "anon_queue"):
        cols = await _columns(conn, "anon_queue")
        if "queued_at" not in cols:
            await _add_column(conn, "anon_queue", "queued_at", "INTEGER DEFAULT 0")
            if "created_at" in cols:
                await conn.execute(
                    """
                    UPDATE anon_queue SET queued_at = COALESCE(created_at, 0)
                    WHERE queued_at IS NULL OR queued_at = 0
                    """
                )

    # 3. anon_sessions
    if await _table_exists(conn, "anon_sessions"):
        cols = await _columns(conn, "anon_sessions")
        await _add_column(conn, "anon_sessions", "started_at", "INTEGER DEFAULT 0")
        await _add_column(conn, "anon_sessions", "ended_at", "INTEGER")
        if "created_at" in cols:
            await conn.execute(
                """
                UPDATE anon_sessions SET started_at = COALESCE(created_at, 0)
                WHERE started_at IS NULL OR started_at = 0
                """
            )
        if "ended" in cols:
            await conn.execute(
                """
                UPDATE anon_sessions SET ended_at = COALESCE(ended_at,
                    CASE WHEN started_at > 0 THEN started_at ELSE EXTRACT(EPOCH FROM NOW())::INTEGER END)
                WHERE ended = 1 AND ended_at IS NULL
                """
            )

    # 4. Перенос фотогалереи: user_photos -> photos
    if await _table_exists(conn, "user_photos"):
        count = await conn.fetchval("SELECT COUNT(*) FROM photos")
        if count == 0:
            await conn.execute(
                """
                INSERT INTO photos (tg_id, photo_id, position)
                SELECT tg_id, photo_id, position FROM user_photos
                ON CONFLICT DO NOTHING
                """
            )

    # 5. Перенос тикетов: support_tickets -> tickets
    if await _table_exists(conn, "support_tickets"):
        count = await conn.fetchval("SELECT COUNT(*) FROM tickets")
        if count == 0:
            old_cols = await _columns(conn, "support_tickets")
            text_col = "message" if "message" in old_cols else "text"
            reply_col = "admin_reply" if "admin_reply" in old_cols else "reply"
            await conn.execute(
                f"""
                INSERT INTO tickets (id, tg_id, category, text, photo_id, reply, status, created_at)
                SELECT id, tg_id, category, {text_col}, photo_id, {reply_col},
                status, created_at FROM support_tickets
                ON CONFLICT DO NOTHING
                """
            )


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

-- Индексы
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
