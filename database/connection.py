"""
database/connection.py
Фикс: aiosqlite-соединение создавалось в одном потоке, а использовалось
в хендлерах из другого -> "SQLite objects created in a thread can only be
used in that same thread". Держим один connection на процесс внутри event loop.
"""
import os, asyncio, logging
from pathlib import Path
import aiosqlite

logger = logging.getLogger("iskra.db")

DB_PATH = os.getenv("DB_PATH", "/data/iskra.db")
SCHEMA_PATH = os.getenv("SCHEMA_PATH", "/app/database/schema.sql")
MIGRATIONS_DIR = os.getenv("MIGRATIONS_DIR", "/app/database/migrations")

_conn: aiosqlite.Connection | None = None
_lock = asyncio.Lock()
_schema_ready = False


async def _configure_conn(conn: aiosqlite.Connection) -> None:
    conn.isolation_level = None            # autocommit; транзакции через BEGIN
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA busy_timeout=5000;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = aiosqlite.Row
    await conn.commit()


async def _ensure_pool() -> aiosqlite.Connection:
    global _conn
    if _conn is not None:
        return _conn
    async with _lock:
        if _conn is not None:
            return _conn
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False -> aiosqlite гоняет вызовы в своём воркере,
        # а мы держим ОДИН экземпляр на процесс в этом event loop.
        conn = await aiosqlite.connect(DB_PATH, check_same_thread=False)
        await _configure_conn(conn)
        _conn = conn
        logger.info("Соединение с SQLite создано: %s", DB_PATH)
        return _conn


async def _apply_migrations(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.commit()
    mig_dir = Path(MIGRATIONS_DIR)
    if not mig_dir.exists():
        return
    for path in sorted(mig_dir.glob("*.sql")):
        cur = await conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?", (path.name,))
        row = await cur.fetchone()
        await cur.close()
        if row:
            continue
        logger.info("Applying migration: %s", path.name)
        await conn.executescript(path.read_text(encoding="utf-8"))
        await conn.execute(
            "INSERT INTO schema_migrations (name) VALUES (?)", (path.name,))
        await conn.commit()
        logger.info("Migration applied: %s", path.name)


async def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    conn = await _ensure_pool()
    logger.info("Инициализация схемы БД...")
    sf = Path(SCHEMA_PATH)
    if sf.exists():
        await conn.executescript(sf.read_text(encoding="utf-8"))
        logger.info("Схема БД загружена из %s", SCHEMA_PATH)
    await _apply_migrations(conn)
    await conn.commit()
    _schema_ready = True
    logger.info("Схема БД инициализирована")


async def wait_until_db_ready(timeout: float = 30.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    last_err: Exception | None = None
    while loop.time() < deadline:
        try:
            await _ensure_schema()
            conn = await _ensure_pool()
            await conn.execute("SELECT 1")
            logger.info("DB ready (wait_until_db_ready succeeded)")
            return
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5)
    logger.error("wait_until_db_ready: timeout: %s", last_err)
    raise last_err if last_err else TimeoutError("DB not ready")


async def get_conn() -> aiosqlite.Connection:
    await _ensure_schema()
    return await _ensure_pool()


async def close_db() -> None:
    global _conn, _schema_ready
    if _conn is not None:
        await _conn.close()
        _conn = None
        _schema_ready = False
