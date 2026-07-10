"""Подключение к БД (SQLite через aiosqlite): пул соединений + изоляция транзакций.

ГЛАВНЫЙ ФИКС (устранение общего соединения под конкурентной нагрузкой):

Раньше на весь процесс жило ОДНО shared-соединение `_conn`, а вебхук
обрабатывает до 100 апдейтов одновременно. Каждый блок `db()` в конце звал
`conn.commit()` — то есть параллельные корутины коммитили чужие незавершённые
записи. Любые «атомарные» read-modify-write (мэтчи в like_repo, reveal в
anon_repo, рейтинг) на деле не были изолированы: между SELECT и INSERT мог
влезть другой апдейт → гонки, дубли, порча счётчиков.

Теперь:
  • Пул из POOL_SIZE отдельных соединений (asyncio.Queue). Каждый блок `db()`
    берёт СВОЁ соединение → своя транзакция, никто не коммитит чужое.
  • WAL позволяет много параллельных читателей + одного писателя.
  • Записи (`db()` по умолчанию, write=True) сериализуются глобальным
    asyncio-локом и идут в режиме BEGIN IMMEDIATE — это даёт настоящую
    атомарность read-modify-write и убирает «database is locked».
  • Чистые чтения можно звать как `db(write=False)` — они идут параллельно,
    без глобального лока (лента, статистика). Существующий код при этом
    остаётся корректным: по умолчанию write=True (безопасная сторона).

Совместимость: сигнатура `async with db() as conn` не изменилась, поэтому
репозитории править не нужно. get_single_db/release_db/wait_until_db_ready/
close_db_pool/ping_db/init_schema сохранены.
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

# Размер пула. Записи всё равно сериализуются (SQLite = один писатель),
# пул нужен в основном для параллельных чтений в WAL.
POOL_SIZE = 8

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"

_pool: "asyncio.Queue[aiosqlite.Connection]" = asyncio.Queue()
_all_conns: list[aiosqlite.Connection] = []
_pool_lock = asyncio.Lock()
_write_lock = asyncio.Lock()  # сериализует писателей в пределах процесса
_pool_ready = False

_schema_ready = False
_schema_lock = asyncio.Lock()


async def _configure_conn(conn: aiosqlite.Connection) -> None:
    """PRAGMA-настройки соединения. isolation_level=None → ручное управление BEGIN/COMMIT."""
    conn.row_factory = aiosqlite.Row
    conn.isolation_level = None  # autocommit; транзакции открываем явно
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")


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
                log.info("Схема БД загружена из %s", SCHEMA_FILE)
            except Exception as e:
                log.error("Ошибка выполнения schema.sql: %s", e)
                raise
    else:
        log.warning("schema.sql не найден: %s", SCHEMA_FILE)

    await _run_migrations(conn)
    log.info("Схема БД готова")


async def _ensure_schema() -> None:
    """Гарантирует инициализацию схемы ровно один раз (на выделенном соединении)."""
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        await _ensure_pool()
        # Схему прогоняем под write-локом на отдельном соединении, чтобы
        # никакая другая корутина не писала параллельно во время миграций.
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

    write=True (по умолчанию): транзакция BEGIN IMMEDIATE под глобальным
      write-локом — атомарный read-modify-write, без гонок и «database is locked».
    write=False: параллельное чтение в WAL без глобального лока (лента, статистика).

    Совместимо со старым `async with db() as conn`.
    """
    await _ensure_schema()

    if write:
        async with _write_lock:
            conn = await _pool.get()
            try:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                    await conn.execute("COMMIT")
                except BaseException:
                    try:
                        await conn.execute("ROLLBACK")
                    except Exception as e:
                        log.warning("ROLLBACK failed: %s", e)
                    raise
            finally:
                _pool.put_nowait(conn)
    else:
        conn = await _pool.get()
        try:
            yield conn  # чистое чтение, транзакцию не открываем
        finally:
            _pool.put_nowait(conn)


async def get_single_db() -> aiosqlite.Connection:
    """DEPRECATED-совместимость: отдаёт соединение из пула (без возврата в пул).

    Оставлено для старого кода. Предпочитайте `async with db() as conn`.
    Полученное соединение НЕ участвует в пуле до release_db().
    """
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
    # Очищаем очередь
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
