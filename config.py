"""Подключение к БД (SQLite через aiosqlite) с пулом соединений.

FIX: пул из DB_POOL_SIZE соединений вместо одного общего _conn — устраняет
     гонку commit/rollback между параллельными webhook-хендлерами.
FIX: db() коммитит/откатывает только своё соединение и возвращает его в пул.
FIX: get_single_db() открывает отдельное соединение, release_db() его закрывает.
"""
import asyncio
import logging
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiosqlite

from config import DB_PATH, DB_POOL_SIZE

log = logging.getLogger("iskra.db")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"

_pool: "Optional[asyncio.Queue[aiosqlite.Connection]]" = None
_pool_conns: list[aiosqlite.Connection] = []
_pool_lock = asyncio.Lock()
_schema_ready = False
_schema_lock = asyncio.Lock()


async def _configure_conn(conn: aiosqlite.Connection) -> None:
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")


async def _new_conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(DB_PATH)
    await _configure_conn(conn)
    return conn


async def _init_pool() -> None:
    global _pool
    if _pool is not None:
        return
    async with _pool_lock:
        if _pool is not None:
            return
        size = max(1, DB_POOL_SIZE)
        pool: "asyncio.Queue[aiosqlite.Connection]" = asyncio.Queue(maxsize=size)
        for _ in range(size):
            conn = await _new_conn()
            _pool_conns.append(conn)
            pool.put_nowait(conn)
        _pool = pool
        log.info("Пул соединений SQLite создан: %s (size=%d)", DB_PATH, size)


async def _run_migrations(conn: aiosqlite.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL UNIQUE,
            applied_at INTEGER NOT NULL
        )
    """)
    await conn.commit()

    cursor = await conn.execute("SELECT filename FROM _migrations")
    applied = {row[0] for row in await cursor.fetchall()}

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
    log.info("Инициализация схемы БД...")
    if SCHEMA_FILE.exists():
        schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
        if "CREATE" not in schema_sql.upper():
            log.warning("schema.sql не содержит валидного SQL, пропускаем: %s", SCHEMA_FILE)
        else:
            try:
                await conn.executescript(schema_sql)
                await conn.commit()
                log.info("Схема БД загружена из %s", SCHEMA_FILE)
            except Exception as e:
                log.error("Ошибка выполнения schema.sql: %s", e)
                raise
    else:
        log.warning("schema.sql не найден: %s", SCHEMA_FILE)

    await _run_migrations(conn)
    log.info("Схема БД готова")


async def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    await _init_pool()
    async with _schema_lock:
        if _schema_ready:
            return
        conn = await _pool.get()
        try:
            await init_schema(conn)
        finally:
            _pool.put_nowait(conn)
        _schema_ready = True
        log.info("Схема БД инициализирована")


@asynccontextmanager
async def db() -> AsyncGenerator[aiosqlite.Connection, None]:
    await _ensure_schema()
    conn = await _pool.get()
    try:
        yield conn
        await conn.commit()
    except BaseException:
        await conn.rollback()
        raise
    finally:
        _pool.put_nowait(conn)


async def get_single_db() -> aiosqlite.Connection:
    await _ensure_schema()
    return await _new_conn()


async def release_db(conn: aiosqlite.Connection) -> None:
    try:
        await conn.close()
    except Exception as e:
        log.warning("Failed to close single db conn: %s", e)


async def close_db_pool() -> None:
    global _pool, _schema_ready
    if _pool is None:
        return
    for conn in _pool_conns:
        try:
            await conn.close()
        except Exception as e:
            log.warning("Failed to close pooled conn: %s", e)
    _pool_conns.clear()
    _pool = None
    _schema_ready = False
    log.info("Пул соединений SQLite закрыт")


async def wait_until_db_ready(timeout: float = 60.0) -> None:
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


async def ping_db() -> bool:
    try:
        await _ensure_schema()
        conn = await _pool.get()
        try:
            await conn.execute("SELECT 1")
        finally:
            _pool.put_nowait(conn)
        return True
    except aiosqlite.Error as e:
        log.warning("DB ping failed (aiosqlite): %s", e)
        return False
    except Exception as e:
        log.warning("DB ping failed (unexpected): %s", e)
        return False
