"""Подключение к БД (SQLite через aiosqlite): пул соединений.

ГЛАВНЫЙ ФИКС (общее соединение): раньше на весь процесс жило ОДНО соединение,
и параллельные корутины коммитили чужие незавершённые записи. Теперь пул из
POOL_SIZE отдельных соединений — каждый блок db() берёт своё, значит свою
transaction, и коммитит только себя. Это и решает исходную проблему.

FIX (лаги): убран глобальный write-лок. Он сериализовал ВСЕ обращения (а db()
по умолчанию write=True, его дёргают touch_activity, чтения репозиториев и т.д.),
из-за чего всё вставало в одну очередь → лаги под нагрузкой. Сериализацию
записи бесплатно обеспечивает сам SQLite в режиме WAL: один писатель за раз,
остальные ждут по busy_timeout. Чтения идут параллельно по разным соединениям.

FIX (thread error): НЕ трогаем conn.isolation_level напрямую (падало с
"SQLite objects created in a thread..."). Используем стандартный режим
aiosqlite: DML авто-открывает транзакцию, commit()/rollback() закрывают её.

FIX (transaction isolation): Добавлен _reset_conn() — перед возвратом соединения
в пул делается ROLLBACK, чтобы сбросить любое pending-состояние (в т.ч. если
предыдущий пользователь забыл закоммитить или использовал write=False после
DML). Также проверяем, что соединение живое, иначе создаём новое.

Совместимость: `async with db() as conn` не изменился. Параметр write оставлен:
  write=True  → по завершении блока commit() (по умолчанию, безопасно);
  write=False → без commit (чистые чтения; чуть дешевле).
Оба варианта берут отдельное соединение из пула и работают параллельно.
"""
import asyncio
import logging
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite

from config import DB_PATH

log = logging.getLogger("iskra.db")

POOL_SIZE = 8

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"

_pool: "asyncio.Queue[aiosqlite.Connection]" = asyncio.Queue()
_all_conns: list[aiosqlite.Connection] = []
_pool_lock = asyncio.Lock()
_pool_ready = False

_schema_ready = False
_schema_lock = asyncio.Lock()


async def _configure_conn(conn: aiosqlite.Connection) -> None:
    """PRAGMA через execute() (уходит в поток соединения). isolation_level не трогаем."""
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")  # ждём до 5с, если пишет другой
    await conn.commit()


async def _create_connection() -> aiosqlite.Connection:
    """Создаёт и конфигурирует новое соединение с БД."""
    conn = await aiosqlite.connect(DB_PATH)
    await _configure_conn(conn)
    return conn


async def _reset_conn(conn: aiosqlite.Connection) -> aiosqlite.Connection:
    """Сбрасывает состояние соединения перед возвратом в пул.

    Делает ROLLBACK, чтобы гарантированно сбросить любую pending-транзакцию
    (если предыдущий пользователь забыл закоммитить или использовал write=False
    после DML). Если соединение мёртвое — создаёт новое.
    """
    try:
        # Проверяем, что соединение ещё открыто
        await conn.execute("SELECT 1")
    except Exception:
        log.warning("Connection is dead, creating new one")
        try:
            await conn.close()
        except Exception:
            pass
        return await _create_connection()

    try:
        # Сбрасываем любое pending-состояние транзакции
        await conn.rollback()
    except Exception:
        # Если rollback не сработал — соединение в плохом состоянии
        log.warning("Rollback failed, replacing connection")
        try:
            await conn.close()
        except Exception:
            pass
        return await _create_connection()

    return conn


async def _ensure_pool() -> None:
    """Лениво создаёт пул соединений один раз."""
    global _pool_ready
    if _pool_ready:
        return
    async with _pool_lock:
        if _pool_ready:
            return
        for _ in range(POOL_SIZE):
            conn = await _create_connection()
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

    Берёт СВОЁ соединение из пула → своя транзакция, не пересекается с чужими.
    write=True (по умолчанию): по завершении блока commit().
    write=False: без commit (чистые чтения, чуть дешевле).

    Сериализацию одновременных записей обеспечивает SQLite (WAL + busy_timeout),
    поэтому глобального питоновского лока нет — чтения и запись идут параллельно.
    """
    await _ensure_schema()
    conn = await _pool.get()
    try:
        yield conn
        if write:
            await conn.commit()
    except BaseException:
        try:
            await conn.rollback()
        except Exception as e:
            log.warning("rollback failed: %s", e)
        raise
    finally:
        # Сбрасываем состояние соединения перед возвратом в пул.
        # Это гарантирует, что следующий пользователь получит чистое соединение
        # без pending-транзакций от предыдущего.
        conn = await _reset_conn(conn)
        _pool.put_nowait(conn)


async def get_single_db() -> aiosqlite.Connection:
    """Совместимость: берёт соединение из пула (вернуть через release_db)."""
    await _ensure_schema()
    return await _pool.get()


async def release_db(conn: aiosqlite.Connection) -> None:
    """Возвращает соединение, взятое через get_single_db(), обратно в пул."""
    if conn is not None:
        conn = await _reset_conn(conn)
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
    """Проверяет живость соединения с БД (чтение)."""
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
