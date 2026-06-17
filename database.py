"""Слой базы данных (SQLite через aiosqlite)."""
import os
import time
from typing import Any, Optional

import aiosqlite

from config import DB_PATH

_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        # Гарантируем существование папки для базы (важно для Volume в /data)
        parent = os.path.dirname(os.path.abspath(DB_PATH))
        if parent:
            os.makedirs(parent, exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL;")
        await _db.execute("PRAGMA foreign_keys=ON;")
    return _db


async def init_db() -> None:
    db = await get_db()
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            tg_id       INTEGER PRIMARY KEY,
            username    TEXT,
            name        TEXT,
            age         INTEGER,
            gender      TEXT,            -- 'm' / 'f'
            seeking     TEXT,            -- 'm' / 'f' / 'any'
            city        TEXT,
            bio         TEXT,
            photo_id    TEXT,
            interests   TEXT DEFAULT '', -- индексы интересов через запятую
            daily_q     INTEGER,         -- индекс дня, на который отвечали
            daily_a     TEXT,            -- ответ на вопрос дня
            active      INTEGER DEFAULT 1,
            is_banned   INTEGER DEFAULT 0,
            streak      INTEGER DEFAULT 0,
            last_active INTEGER DEFAULT 0,
            rating      INTEGER DEFAULT 0, -- сколько лайков получил всего
            shown       INTEGER DEFAULT 0,
            min_age     INTEGER DEFAULT 18,
            max_age     INTEGER DEFAULT 99,
            created_at  INTEGER
        );

        CREATE TABLE IF NOT EXISTS likes (
            from_id  INTEGER,
            to_id    INTEGER,
            is_like  INTEGER,   -- 1 лайк, 0 дизлайк
            seen     INTEGER DEFAULT 0,
            created_at INTEGER,
            PRIMARY KEY (from_id, to_id)
        );

        CREATE INDEX IF NOT EXISTS idx_likes_to ON likes(to_id, is_like);

        CREATE TABLE IF NOT EXISTS matches (
            a_id INTEGER,
            b_id INTEGER,
            created_at INTEGER,
            PRIMARY KEY (a_id, b_id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            from_id INTEGER,
            to_id   INTEGER,
            created_at INTEGER
        );

        -- Свидание вслепую: очередь ожидания и активные анонимные сессии
        CREATE TABLE IF NOT EXISTS anon_queue (
            tg_id      INTEGER PRIMARY KEY,
            created_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS anon_sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            a_id       INTEGER,
            b_id       INTEGER,
            a_reveal   INTEGER DEFAULT 0,
            b_reveal   INTEGER DEFAULT 0,
            ended      INTEGER DEFAULT 0,
            created_at INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_anon_active ON anon_sessions(ended);
        """
    )
    await db.commit()


# ---------- Пользователи ----------

async def get_user(tg_id: int) -> Optional[aiosqlite.Row]:
    db = await get_db()
    cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
    return await cur.fetchone()


async def upsert_user(tg_id: int, **fields: Any) -> None:
    db = await get_db()
    existing = await get_user(tg_id)
    if existing is None:
        fields.setdefault("created_at", int(time.time()))
        cols = ", ".join(["tg_id", *fields.keys()])
        ph = ", ".join(["?"] * (len(fields) + 1))
        await db.execute(
            f"INSERT INTO users ({cols}) VALUES ({ph})",
            (tg_id, *fields.values()),
        )
    else:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        await db.execute(
            f"UPDATE users SET {sets} WHERE tg_id = ?",
            (*fields.values(), tg_id),
        )
    await db.commit()


async def delete_user(tg_id: int) -> None:
    """Полное удаление аккаунта: убираем пользователя из всех таблиц."""
    db = await get_db()
    await db.execute("DELETE FROM anon_queue WHERE tg_id = ?", (tg_id,))
    await db.execute(
        "UPDATE anon_sessions SET ended = 1 WHERE (a_id = ? OR b_id = ?) AND ended = 0",
        (tg_id, tg_id),
    )
    await db.execute("DELETE FROM matches WHERE a_id = ? OR b_id = ?", (tg_id, tg_id))
    await db.execute("DELETE FROM likes WHERE from_id = ? OR to_id = ?", (tg_id, tg_id))
    await db.execute("DELETE FROM reports WHERE from_id = ? OR to_id = ?", (tg_id, tg_id))
    await db.execute("DELETE FROM users WHERE tg_id = ?", (tg_id,))
    await db.commit()


async def set_active(tg_id: int, active: bool) -> None:
    await upsert_user(tg_id, active=1 if active else 0)


async def touch_activity(tg_id: int) -> None:
    """Обновляем стрик активности (раз в сутки +1, если пропуск >2 дней — сброс)."""
    db = await get_db()
    user = await get_user(tg_id)
    if user is None:
        return
    now = int(time.time())
    last = user["last_active"] or 0
    day = 86400
    streak = user["streak"] or 0
    if now - last >= day:
        if now - last <= 2 * day:
            streak += 1
        else:
            streak = 1
        await db.execute(
            "UPDATE users SET streak = ?, last_active = ? WHERE tg_id = ?",
            (streak, now, tg_id),
        )
        await db.commit()


# ---------- Лента ----------

async def next_candidate(tg_id: int) -> Optional[aiosqlite.Row]:
    """Следующая анкета для показа с учётом фильтров пола/возраста."""
    db = await get_db()
    me = await get_user(tg_id)
    if me is None:
        return None

    seeking = me["seeking"] or "any"
    gender_clause = "" if seeking == "any" else "AND u.gender = :seeking"
    # Кого хотят видеть встречные анкеты — пусть тоже совпадает по возможности
    cur = await db.execute(
        f"""
        SELECT u.* FROM users u
        WHERE u.tg_id != :me
          AND u.active = 1
          AND u.is_banned = 0
          AND u.age BETWEEN :min_age AND :max_age
          {gender_clause}
          AND (u.seeking = 'any' OR u.seeking = :my_gender)
          AND u.tg_id NOT IN (SELECT to_id FROM likes WHERE from_id = :me)
        ORDER BY u.last_active DESC, u.shown ASC, RANDOM()
        LIMIT 1
        """,
        {
            "me": tg_id,
            "seeking": seeking,
            "my_gender": me["gender"],
            "min_age": me["min_age"] or 18,
            "max_age": me["max_age"] or 99,
        },
    )
    return await cur.fetchone()


async def mark_shown(tg_id: int) -> None:
    db = await get_db()
    await db.execute("UPDATE users SET shown = shown + 1 WHERE tg_id = ?", (tg_id,))
    await db.commit()


# ---------- Лайки и мэтчи ----------

async def add_like(from_id: int, to_id: int, is_like: bool) -> bool:
    """Сохраняет реакцию. Возвращает True, если образовался взаимный мэтч."""
    db = await get_db()
    now = int(time.time())
    await db.execute(
        "INSERT OR REPLACE INTO likes (from_id, to_id, is_like, seen, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (from_id, to_id, 1 if is_like else 0, now),
    )
    if is_like:
        await db.execute(
            "UPDATE users SET rating = rating + 1 WHERE tg_id = ?", (to_id,)
        )
    await db.commit()

    if not is_like:
        return False

    cur = await db.execute(
        "SELECT 1 FROM likes WHERE from_id = ? AND to_id = ? AND is_like = 1",
        (to_id, from_id),
    )
    if await cur.fetchone():
        a, b = sorted((from_id, to_id))
        await db.execute(
            "INSERT OR IGNORE INTO matches (a_id, b_id, created_at) VALUES (?, ?, ?)",
            (a, b, now),
        )
        await db.commit()
        return True
    return False


async def incoming_likes(tg_id: int) -> list[aiosqlite.Row]:
    """Кто лайкнул меня, но я ещё не ответил взаимно."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT u.* FROM likes l
        JOIN users u ON u.tg_id = l.from_id
        WHERE l.to_id = ? AND l.is_like = 1
          AND u.active = 1 AND u.is_banned = 0
          AND l.from_id NOT IN (
                SELECT to_id FROM likes WHERE from_id = ? AND is_like = 1
          )
        ORDER BY l.created_at DESC
        """,
        (tg_id, tg_id),
    )
    return await cur.fetchall()


async def count_incoming_likes(tg_id: int) -> int:
    rows = await incoming_likes(tg_id)
    return len(rows)


async def get_matches(tg_id: int) -> list[aiosqlite.Row]:
    db = await get_db()
    cur = await db.execute(
        """
        SELECT u.* FROM matches m
        JOIN users u ON u.tg_id = (CASE WHEN m.a_id = ? THEN m.b_id ELSE m.a_id END)
        WHERE (m.a_id = ? OR m.b_id = ?)
          AND u.is_banned = 0
        ORDER BY m.created_at DESC
        """,
        (tg_id, tg_id, tg_id),
    )
    return await cur.fetchall()


# ---------- Жалобы ----------

async def add_report(from_id: int, to_id: int) -> int:
    db = await get_db()
    now = int(time.time())
    await db.execute(
        "INSERT INTO reports (from_id, to_id, created_at) VALUES (?, ?, ?)",
        (from_id, to_id, now),
    )
    # Дизлайкаем заодно, чтобы не показывать снова
    await db.execute(
        "INSERT OR REPLACE INTO likes (from_id, to_id, is_like, seen, created_at) "
        "VALUES (?, ?, 0, 1, ?)",
        (from_id, to_id, now),
    )
    cur = await db.execute(
        "SELECT COUNT(*) AS c FROM reports WHERE to_id = ?", (to_id,)
    )
    row = await cur.fetchone()
    count = row["c"] if row else 0
    if count >= 5:
        await db.execute("UPDATE users SET is_banned = 1 WHERE tg_id = ?", (to_id,))
    await db.commit()
    return count


# ---------- Свидание вслепую (анонимный чат) ----------

async def anon_session_of(tg_id: int) -> Optional[aiosqlite.Row]:
    """Активная (не завершённая) сессия пользователя, если есть."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM anon_sessions WHERE ended = 0 AND (a_id = ? OR b_id = ?) "
        "ORDER BY id DESC LIMIT 1",
        (tg_id, tg_id),
    )
    return await cur.fetchone()


async def anon_active_partner(tg_id: int) -> Optional[int]:
    """ID собеседника в активной сессии или None."""
    s = await anon_session_of(tg_id)
    if not s:
        return None
    return s["b_id"] if s["a_id"] == tg_id else s["a_id"]


async def anon_in_queue(tg_id: int) -> bool:
    db = await get_db()
    cur = await db.execute("SELECT 1 FROM anon_queue WHERE tg_id = ?", (tg_id,))
    return await cur.fetchone() is not None


async def anon_leave_queue(tg_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM anon_queue WHERE tg_id = ?", (tg_id,))
    await db.commit()


async def anon_find_or_queue(tg_id: int) -> tuple[str, Optional[int]]:
    """Подбор собеседника для «Свидания вслепую».

    Возвращает (status, partner_id):
      'in_session' — уже в активном чате (partner_id — собеседник)
      'matched'    — нашли собеседника, создана сессия (partner_id)
      'queued'     — добавлены в очередь ожидания (None)
      'waiting'    — уже стояли в очереди (None)
    """
    db = await get_db()
    partner = await anon_active_partner(tg_id)
    if partner is not None:
        return "in_session", partner

    # Ищем ожидающего собеседника (не себя, активного, не забаненного)
    cur = await db.execute(
        """
        SELECT q.tg_id FROM anon_queue q
        JOIN users u ON u.tg_id = q.tg_id
        WHERE q.tg_id != ? AND u.is_banned = 0 AND u.name IS NOT NULL
        ORDER BY q.created_at ASC LIMIT 1
        """,
        (tg_id,),
    )
    row = await cur.fetchone()
    if row is not None:
        pid = row["tg_id"]
        now = int(time.time())
        await db.execute("DELETE FROM anon_queue WHERE tg_id IN (?, ?)", (pid, tg_id))
        await db.execute(
            "INSERT INTO anon_sessions (a_id, b_id, created_at) VALUES (?, ?, ?)",
            (tg_id, pid, now),
        )
        await db.commit()
        return "matched", pid

    # Никого нет — встаём в очередь
    if await anon_in_queue(tg_id):
        return "waiting", None
    await db.execute(
        "INSERT OR REPLACE INTO anon_queue (tg_id, created_at) VALUES (?, ?)",
        (tg_id, int(time.time())),
    )
    await db.commit()
    return "queued", None


async def anon_set_reveal(tg_id: int) -> Optional[aiosqlite.Row]:
    """Помечает желание открыться. Возвращает свежую строку сессии."""
    db = await get_db()
    s = await anon_session_of(tg_id)
    if not s:
        return None
    col = "a_reveal" if s["a_id"] == tg_id else "b_reveal"
    await db.execute(f"UPDATE anon_sessions SET {col} = 1 WHERE id = ?", (s["id"],))
    await db.commit()
    cur = await db.execute("SELECT * FROM anon_sessions WHERE id = ?", (s["id"],))
    return await cur.fetchone()


async def anon_end(tg_id: int) -> Optional[int]:
    """Завершает активную сессию и убирает из очереди. Возвращает id собеседника."""
    db = await get_db()
    await db.execute("DELETE FROM anon_queue WHERE tg_id = ?", (tg_id,))
    s = await anon_session_of(tg_id)
    if not s:
        await db.commit()
        return None
    partner = s["b_id"] if s["a_id"] == tg_id else s["a_id"]
    await db.execute("UPDATE anon_sessions SET ended = 1 WHERE id = ?", (s["id"],))
    await db.commit()
    return partner


async def stats() -> dict:
    db = await get_db()
    out: dict = {}
    for key, q in {
        "users": "SELECT COUNT(*) c FROM users",
        "active": "SELECT COUNT(*) c FROM users WHERE active = 1",
        "matches": "SELECT COUNT(*) c FROM matches",
        "likes": "SELECT COUNT(*) c FROM likes WHERE is_like = 1",
    }.items():
        cur = await db.execute(q)
        row = await cur.fetchone()
        out[key] = row["c"] if row else 0
    return out
