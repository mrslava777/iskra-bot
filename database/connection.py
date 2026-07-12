"""SQLite через aiosqlite: изолированный пул соединений и миграции.

Каждый блок ``async with db()`` получает отдельное соединение, поэтому
commit/rollback одного webhook-хендлера не затрагивает другие корутины.
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

_pool: Optional[asyncio.Queue[aiosqlite.Connection]] = None
_live_connections: set[aiosqlite.Connection] = set()
_pool_lock = asyncio.Lock()
_pool_ready = False

_schema_ready = False
_schema_lock = asyncio.Lock()


def _prepare_db_directory() -> None:
    if DB_PATH == ":memory:" or DB_PATH.startswith("file:"):
        return
    parent = Path(DB_PATH).expanduser().parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


async def _configure_conn(conn: aiosqlite.Connection) -> None:
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=10000")
    await conn.commit()


async def _create_connection() -> aiosqlite.Connection:
    _prepare_db_directory()
    conn = await aiosqlite.connect(DB_PATH)
    try:
        await _configure_conn(conn)
    except BaseException:
        await conn.close()
        raise
    _live_connections.add(conn)
    return conn


async def _discard_connection(conn: aiosqlite.Connection) -> None:
    _live_connections.discard(conn)
    try:
        await conn.close()
    except Exception:
        pass


async def _ensure_pool() -> None:
    global _pool, _pool_ready
    if _pool_ready:
        return

    async with _pool_lock:
        if _pool_ready:
            return

        queue: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(
            maxsize=DB_POOL_SIZE
        )
        created: list[aiosqlite.Connection] = []
        try:
            for _ in range(DB_POOL_SIZE):
                conn = await _create_connection()
                created.append(conn)
                queue.put_nowait(conn)
        except BaseException:
            for conn in created:
                await _discard_connection(conn)
            raise

        _pool = queue
        _pool_ready = True
        log.info("Пул SQLite готов: %s (size=%d)", DB_PATH, DB_POOL_SIZE)


async def _reset_or_replace(
    conn: aiosqlite.Connection,
) -> Optional[aiosqlite.Connection]:
    """Откатывает незавершённую транзакцию и проверяет соединение."""
    try:
        await conn.rollback()
        cursor = await conn.execute("SELECT 1")
        await cursor.fetchone()
        return conn
    except BaseException as exc:
        log.warning("Соединение SQLite повреждено, заменяем: %s", exc)
        await _discard_connection(conn)
        if not _pool_ready:
            return None
        return await _create_connection()


async def _return_to_pool(conn: aiosqlite.Connection) -> None:
    if not _pool_ready or _pool is None:
        await _discard_connection(conn)
        return

    clean = await _reset_or_replace(conn)
    if clean is None:
        return
    try:
        _pool.put_nowait(clean)
    except asyncio.QueueFull:
        # Это означает ошибку учёта, но соединение всё равно не должно утечь.
        log.error("Пул SQLite переполнен при возврате соединения")
        await _discard_connection(clean)


async def _run_migrations(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL UNIQUE,
            applied_at INTEGER NOT NULL
        )
        """
    )
    await conn.commit()

    cursor = await conn.execute("SELECT filename FROM _migrations")
    applied = {row[0] for row in await cursor.fetchall()}

    migration_files = (
        sorted(
            file
            for file in MIGRATIONS_DIR.iterdir()
            if file.suffix == ".sql" and file.name not in applied
        )
        if MIGRATIONS_DIR.exists()
        else []
    )

    for migration_file in migration_files:
        log.info("Применяю миграцию: %s", migration_file.name)
        sql = migration_file.read_text(encoding="utf-8")
        try:
            await conn.executescript(sql)
            await conn.execute(
                "INSERT INTO _migrations (filename, applied_at) VALUES (?, ?)",
                (migration_file.name, int(_time.time())),
            )
            await conn.commit()
        except BaseException:
            await conn.rollback()
            log.exception("Миграция завершилась ошибкой: %s", migration_file.name)
            raise


async def init_schema(conn: aiosqlite.Connection) -> None:
    if not SCHEMA_FILE.exists():
        raise RuntimeError(f"Файл схемы БД не найден: {SCHEMA_FILE}")

    schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
    if "CREATE" not in schema_sql.upper():
        raise RuntimeError(f"Файл схемы не содержит SQL: {SCHEMA_FILE}")

    await conn.executescript(schema_sql)
    await conn.commit()
    await _run_migrations(conn)
    log.info("Схема БД и миграции готовы")


async def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return

    await _ensure_pool()
    async with _schema_lock:
        if _schema_ready:
            return
        assert _pool is not None
        conn = await _pool.get()
        try:
            await init_schema(conn)
            _schema_ready = True
        except BaseException:
            try:
                await conn.rollback()
            except Exception:
                pass
            raise
        finally:
            await _return_to_pool(conn)


@asynccontextmanager
async def db(
    write: bool = True,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Выдаёт изолированное соединение из пула.

    ``write=True`` коммитит изменения при успешном выходе.
    ``write=False`` предназначен для чистого чтения; любые случайные изменения
    будут откатаны при возврате соединения в пул.
    """
    await _ensure_schema()
    assert _pool is not None
    conn = await _pool.get()
    try:
        yield conn
        if write:
            await conn.commit()
        else:
            await conn.rollback()
    except BaseException:
        try:
            await conn.rollback()
        except Exception as rollback_error:
            log.warning("Rollback SQLite не удался: %s", rollback_error)
        raise
    finally:
        await _return_to_pool(conn)


async def get_single_db() -> aiosqlite.Connection:
    """Берёт соединение из пула; вернуть через ``release_db``."""
    await _ensure_schema()
    assert _pool is not None
    return await _pool.get()


async def release_db(conn: aiosqlite.Connection) -> None:
    if conn is not None:
        await _return_to_pool(conn)


async def close_db_pool() -> None:
    """Закрывает все соединения, включая временно выданные."""
    global _pool, _pool_ready, _schema_ready

    async with _pool_lock:
        _pool_ready = False
        _schema_ready = False
        connections = list(_live_connections)
        _pool = None
        for conn in connections:
            await _discard_connection(conn)
        log.info("Пул SQLite закрыт")


async def wait_until_db_ready(timeout: float = 60.0) -> None:
    deadline = _time.monotonic() + timeout
    last_error: Optional[BaseException] = None

    while _time.monotonic() < deadline:
        try:
            await _ensure_schema()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.5)

    raise TimeoutError("База данных не готова за отведённое время") from last_error


async def ping_db() -> bool:
    try:
        async with db(write=False) as conn:
            cursor = await conn.execute("SELECT 1")
            await cursor.fetchone()
        return True
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("DB ping failed: %s", exc)
        return False
