"""Подключение к БД (SQLite через aiosqlite): пул соединений + сериализация записи.

ГЛАВНЫЙ ФИКС (общее соединение под конкурентной нагрузкой):
Раньше на весь процесс жило ОДНО соединение, и параллельные корутины
коммитили чужие незавершённые записи. Теперь пул из POOL_SIZE отдельных
соединений: каждый блок db() берёт своё, значит свою транзакцию.

FIX (thread error): НЕ трогаем conn.isolation_level напрямую (это лезет в
sqlite-объект из чужого потока → "SQLite objects created in a thread can only
be used in that same thread"). Оставляем стандартный режим aiosqlite: DML
авто-открывает транзакцию, а conn.commit()/rollback() её закрывают. PRAGMA
выставляем через conn.execute() (уходит в worker-поток соединения).

Атомарность read-modify-write обеспечивается глобальным write-локом: писатели
идут строго по одному, каждый на своём соединении, и коммитят только себя.
Гонок и "database is locked" нет.

Совместимость: `async with db() as conn` не изменился (write=True по умолчанию).
Чистые чтения можно звать db(write=False) — параллельно, без write-лока.
"""
import asyncio
import logging
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiosqlite

from config import DB_PATH

log = logging.getLogger("iskra.db")

POOL_SIZE = 8

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"

_pool: "asyncio.Queue[aiosqlite.Connection]" = asyncio.Queue()
_all_conns: list[aiosqlite.Connection] = []
_pool_lock = asyncio.Lock()
_write_lock = asyncio.Lock()
_pool_ready = False

_schema_ready = False
_schema_lock = asyncio.Lock()


async def _configure_conn(conn: aiosqlite.Connection) -> None:
    """PRAGMA-настройки. Всё через execute() → выполняется в потоке соединения.

    ВАЖНО: не трогаем conn.isolation_level напрямую — это обращение к sqlite
    из главного потока и падает с thread-ошибкой.
    """
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.commit()


async def _ensure_pool() -> None:
    """Лениво создаёт пул соединений один раз."""
    global _pool_ready
    if _pool_ready:
        return
    async with _pool_lock:
        if _pool_ready:
            return
        for _ in range(POOL_SIZE):
            conn = await aiosqlite.connect(DB_PATH)
            await _configure_conn(conn)
            _all_conns.append(conn)
            _pool.put_nowait(conn)
        _pool_ready = True
        log.info("Соединение с SQLite создано: %s (пул %d)", DB_PATH, POOL_SIZE)


# ── Схема / миграции ──────────────────────────────────────────────

async def _run_migrations(conn: aiosqlite.Connection) -> None:
    """Применяет pending-миграции из database/migrations/."""
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
    """Создаёт таблицы и индексы из schema.sql (идемпотентно) + миграции."""
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
    """Гарантирует инициализацию схемы ровно один раз (на отдельном соединении)."""
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        await _ensure_pool()
        async with _write_lock:
            conn = await aiosqlite.connect(DB_PATH)
            try:
                await _configure_conn(conn)
                await init_schema(conn)
            finally:
                await conn.close()
        _schema_ready = True
        log.info("Схема БД инициализирована")


# ── Публичный контекст-менеджер ───────────────────────────────────

@asynccontextmanager
async def db(write: bool = True) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Контекстный менеджер для работы с БД.

    write=True (по умолчанию): под глобальным write-локом. Писатели идут по
      одному, каждый на своём соединении и коммитит только себя → атомарный
      read-modify-write без гонок.
    write=False: параллельное чтение в WAL без лока (лента, статистика).

    Совместимо со старым `async with db() as conn`.
    """
    await _ensure_schema()

    if write:
        async with _write_lock:
            conn = await _pool.get()
            try:
                yield conn
                await conn.commit()
            except BaseException:
                try:
                    await conn.rollback()
                except Exception as e:
                    log.warning("rollback failed: %s", e)
                raise
            finally:
                _pool.put_nowait(conn)
    else:
        conn = await _pool.get()
        try:
            yield conn
        finally:
            _pool.put_nowait(conn)


async def get_single_db() -> aiosqlite.Connection:
    """Совместимость: берёт соединение из пула (вернуть через release_db)."""
    await _ensure_schema()
    return await _pool.get()


async def release_db(conn: aiosqlite.Connection) -> None:
    """Возвращает соединение, взятое через get_single_db(), обратно в пул."""
    if conn is not None:
        _pool.put_nowait(conn)


async def close_db_pool() -> None:
    """Закрывает все соединения пула (graceful shutdown)."""
    global _pool_ready, _schema_ready
    for conn in _all_conns:
        try:
            await conn.close()
        except Exception as e:
            log.warning("Failed to close pooled conn: %s", e)
    _all_conns.clear()
    while not _pool.empty():
        try:
            _pool.get_nowait()
        except Exception:
            break
    _pool_ready = False
    _schema_ready = False
    log.info("Пул соединений с SQLite закрыт")


async def wait_until_db_ready(timeout: float = 60.0) -> None:
    """Блокирует старт приложения до прогрева схемы БД."""
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
    """Проверяет живость соединения с БД (чтение, без write-лока)."""
    try:
        async with db(write=False) as conn:
            await conn.execute("SELECT 1")
        return True
    except aiosqlite.Error as e:
        log.warning("DB ping failed (aiosqlite): %s", e)
        return False
    except Exception as e:
        log.warning("DB ping failed (unexpected): %s", e)
        return False
