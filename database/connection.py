"""Подключение к БД (PostgreSQL через asyncpg) и инициализация схемы.

Модель доступа:
    get_db()         — соединение для ЧТЕНИЯ (переиспользуется, автопереподключается).
    get_single_db()  — НОВОЕ соединение для ЗАПИСИ; вызывающий закрывает сам.
    close_db_pool()  — закрывает соединение (graceful shutdown).

Схема создаётся один раз при первом get_db().
"""
import logging
import os
from typing import Optional

import asyncpg

from config import DATABASE_URL

log = logging.getLogger("iskra.db")

_db: Optional[asyncpg.Connection] = None
_schema_ready = False


async def _connect() -> asyncpg.Connection:
    """Создаёт новое соединение с PostgreSQL."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан! Добавь переменную окружения DATABASE_URL")

    # Добавляем параметры для стабильности соединения
    dsn = DATABASE_URL
    if "?" not in dsn:
        dsn += "?"
    else:
        dsn += "&"
    dsn += "sslmode=require&keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=5"

    log.info("Подключаюсь к PostgreSQL...")
    conn = await asyncpg.connect(dsn=dsn)
    log.info("Подключено к PostgreSQL")
    return conn


async def get_db() -> asyncpg.Connection:
    """Общее соединение для чтения. Создаёт схему при первом вызове."""
    global _db, _schema_ready

    # Проверяем, живо ли соединение
    if _db is not None:
        try:
            await _db.execute("SELECT 1")
        except Exception:
            log.warning("Соединение с БД разорвано, переподключаюсь...")
            try:
                await _db.close()
            except Exception:
                pass
            _db = None
            _schema_ready = False

    if _db is None:
        _db = await _connect()

    if not _schema_ready:
        try:
            await init_schema(_db)
            _schema_ready = True
            log.info("Схема БД инициализирована")
        except Exception as e:
            log.error("Ошибка инициализации схемы: %s", e)
            raise

    return _db


async def get_single_db() -> asyncpg.Connection:
    """Свежее соединение для записи. Вызывающий обязан закрыть его сам."""
    global _schema_ready
    if not _schema_ready:
        await get_db()
    return await _connect()


async def close_db_pool() -> None:
    """Закрывает соединение (graceful shutdown)."""
    global _db
    if _db is not None:
        try:
            await _db.close()
        except Exception:
            pass
        _db = None
        log.info("Соединение с PostgreSQL закрыто")


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

# Колонки, которые могут отсутствовать в старых версиях таблицы
# (ключ: таблица, значение: список (имя_колонки, тип, default))
MISSING_COLUMNS = {
    "users": [
        ("is_banned", "INTEGER", "0"),
        ("streak", "INTEGER", "0"),
        ("rating", "INTEGER", "0"),
        ("daily_q", "INTEGER", "0"),
        ("daily_a", "TEXT", "''"),
        ("anon_messages_count", "INTEGER", "0"),
        ("min_age", "INTEGER", "18"),
        ("max_age", "INTEGER", "99"),
        ("max_compat", "INTEGER", "0"),
    ]
}


async def _ensure_columns(conn: asyncpg.Connection) -> None:
    """Добавляет недостающие колонки в существующие таблицы."""
    for table, columns in MISSING_COLUMNS.items():
        for col_name, col_type, default in columns:
            try:
                await conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type} DEFAULT {default}"
                )
                log.info("Колонка %s.%s проверена/добавлена", table, col_name)
            except Exception as e:
                log.warning("Не удалось добавить колонку %s.%s: %s", table, col_name, e)


async def init_schema(conn: asyncpg.Connection) -> None:
    """Создаёт все таблицы и индексы (идемпотентно).

    Работает даже если таблицы уже существуют без некоторых колонок.
    """
    log.info("Создаю таблицы...")

    # Шаг 1: Создаём таблицы (если не существуют)
    await conn.execute(SCHEMA_SQL)

    # Шаг 2: Добавляем недостающие колонки (для миграции старых таблиц)
    await _ensure_columns(conn)

    # Шаг 3: Создаём индексы (теперь все колонки гарантированно существуют)
    await conn.execute(INDEX_SQL)

    log.info("Таблицы созданы")
