"""Подключение к БД (SQLite через aiosqlite) и инициализация схемы.

Модель доступа:
    db()             — асинхронный контекстный менеджер для работы с БД.
    get_single_db()  — НОВОЕ соединение для транзакций.
                       Вызывающий обязан вернуть через await release_db(conn).
    close_db_pool()  — закрывает соединение (graceful shutdown).

Схема создаётся один раз при первом вызове db().
Миграции применяются автоматически из database/migrations/.
"""
import asyncio
import logging
import os
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiosqlite

from config import DB_PATH

log = logging.getLogger("iskra.db")

_conn: Optional[aiosqlite.Connection] = None
_conn_lock = asyncio.Lock()
_schema_ready = False
_schema_lock = asyncio.Lock()

# Путь к директории с миграциями
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"


async def _run_migrations(conn: aiosqlite.Connection) -> None:
    """Применяет pending-миграции из database/migrations/."""
    # Создаём таблицу миграций если ещё нет
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            filename   TEXT NOT NULL UNIQUE,
            applied_at INTEGER NOT NULL
        )
    """)
    await conn.commit()

    # Получаем уже применённые миграции
    cursor = await conn.execute("SELECT filename FROM _migrations")
    applied = {row[0] for row in await cursor.fetchall()}

    # Находим новые миграции
    if MIGRATIONS_DIR.exists():
        migration_files = sorted(
            f for f in MIGRATIONS_DIR.iterdir()
            if f.suffix == ".sql" and f.name not in applied
        )
    else:
        migration_files = []

    for mig_file in migration_files:
        log.info("Applying migration: %s", mig_file.name)
        sql = mig_file.read_text(encoding="utf-8")
        await conn.executescript(sql)
        await conn.execute(
            "INSERT INTO _migrations (filename, applied_at) VALUES (?, ?)",
            (mig_file.name, int(_time.time())),
        )
        await conn.commit()
        log.info("Migration applied: %s", mig_file.name)


async def init_schema(conn: aiosqlite.Connection) -> None:
    """Создаёт все таблицы и индексы из schema.sql (идемпотентно)."""
    log.info("Инициализация схемы БД...")
    if SCHEMA_FILE.exists():
        schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
        # FIX: schema.sql может содержать документацию вместо SQL — проверяем
        sql_lines = [ln for ln in schema_sql.splitlines() if ln.strip() and not ln.strip().startswith("--") and not ln.strip().startswith("#")]
        if not sql_lines or "CREATE" not in schema_sql.upper():
            log.warning("schema.sql не содержит валидного SQL, пропускаем: %s", SCHEMA_FILE)
            return
        try:
            await conn.executescript(schema_sql)
            await conn.commit()
            log.info("Схема БД загружена из %s", SCHEMA_FILE)
        except Exception as e:
            log.error("Ошибка выполнения schema.sql: %s", e)
            raise
    else:
        log.warning("schema.sql не найден: %s", SCHEMA_FILE)

    # Применяем миграции
    await _run_migrations(conn)
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
    except aiosqlite.Error:
        await conn.rollback()
        raise
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
    deadline = _time.monotonic() + timeout
    while True:
        try:
            await _ensure_schema()
            return
        except Exception as e:
            if _time.monotonic() > deadline:
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

        # SQLite optimizations for production
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA synchronous=NORMAL")
        await _conn.execute("PRAGMA foreign_keys=ON")
        await _conn.execute("PRAGMA busy_timeout=5000")  # 5 sec timeout
        log.info("Соединение с SQLite создано: %s", DB_PATH)
        return _conn


async def ping_db() -> bool:
    """Проверяет живость соединения с БД."""
    try:
        conn = await _get_conn()
        await conn.execute("SELECT 1")
        return True
    except aiosqlite.Error as e:
        log.warning("DB ping failed (aiosqlite): %s", e)
        return False
    except Exception as e:
        log.warning("DB ping failed (unexpected): %s", e)
        return False
