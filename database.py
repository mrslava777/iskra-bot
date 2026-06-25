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
        """\n        CREATE TABLE IF NOT EXISTS users (\n            tg_id       INTEGER PRIMARY KEY,\n            username    TEXT,\n            name        TEXT,\n            age         INTEGER,\n            gender      TEXT,            -- 'm' / 'f'\n            seeking     TEXT,            -- 'm' / 'f' / 'any'\n            city        TEXT,\n            bio         TEXT,\n            photo_id    TEXT,\n            interests   TEXT DEFAULT '', -- индексы интересов через запятую\n            daily_q     INTEGER,         -- индекс дня, на который отвечали\n            daily_a     TEXT,            -- ответ на вопрос дня\n            active      INTEGER DEFAULT 1,\n            is_banned   INTEGER DEFAULT 0,\n            streak      INTEGER DEFAULT 0,\n            last_active INTEGER DEFAULT 0,\n            rating      INTEGER DEFAULT 0, -- сколько лайков получил всего\n            shown       INTEGER DEFAULT 0,\n            min_age     INTEGER DEFAULT 18,\n            max_age     INTEGER DEFAULT 99,\n            created_at  INTEGER,\n            verified    INTEGER DEFAULT 0,\n            anon_messages_count INTEGER DEFAULT 0  -- счётчик сообщений в анонимном чате\n        );\n\n        CREATE TABLE IF NOT EXISTS likes (\n            from_id  INTEGER,\n            to_id    INTEGER,\n            is_like  INTEGER,   -- 1 лайк, 0 дизлайк\n            seen     INTEGER DEFAULT 0,\n            message  TEXT,      -- сообщение при msglike\n            created_at INTEGER,\n            PRIMARY KEY (from_id, to_id)\n        );\n\n        CREATE INDEX IF NOT EXISTS idx_likes_to ON likes(to_id, is_like);\n\n        CREATE TABLE IF NOT EXISTS matches (\n            a_id INTEGER,\n            b_id INTEGER,\n            created_at INTEGER,\n            PRIMARY KEY (a_id, b_id)\n        );\n\n        CREATE TABLE IF NOT EXISTS reports (\n            from_id INTEGER,\n            to_id   INTEGER,\n            created_at INTEGER\n        );\n\n        -- Свидание вслепую: очередь ожидания и активные анонимные сессии\n        CREATE TABLE IF NOT EXISTS anon_queue (\n            tg_id      INTEGER PRIMARY KEY,\n            created_at INTEGER\n        );\n\n        CREATE TABLE IF NOT EXISTS anon_sessions (\n            id         INTEGER PRIMARY KEY AUTOINCREMENT,\n            a_id       INTEGER,\n            b_id       INTEGER,\n            a_reveal   INTEGER DEFAULT 0,\n            b_reveal   INTEGER DEFAULT 0,\n            ended      INTEGER DEFAULT 0,\n            created_at INTEGER\n        );\n\n        CREATE INDEX IF NOT EXISTS idx_anon_active ON anon_sessions(ended);\n\n        -- Тикеты поддержки\n        CREATE TABLE IF NOT EXISTS support_tickets (\n            id         INTEGER PRIMARY KEY AUTOINCREMENT,\n            tg_id      INTEGER NOT NULL,\n            category   TEXT    NOT NULL,\n            message    TEXT    NOT NULL,\n            photo_id   TEXT,\n            status     TEXT    DEFAULT 'open',  -- open / replied / closed\n            admin_reply TEXT,\n            created_at INTEGER,\n            replied_at INTEGER\n        );\n\n        CREATE INDEX IF NOT EXISTS idx_tickets_status ON support_tickets(status);\n\n        -- Дополнительные фото пользователя (до 5 шт.)\n        CREATE TABLE IF NOT EXISTS user_photos (\n            tg_id      INTEGER NOT NULL,\n            photo_id   TEXT    NOT NULL,\n            position   INTEGER NOT NULL DEFAULT 0,  -- 0..4\n            created_at INTEGER,\n            PRIMARY KEY (tg_id, position)\n        );\n\n        -- Верификация: запросы на проверку\n        CREATE TABLE IF NOT EXISTS verify_requests (\n            tg_id      INTEGER PRIMARY KEY,\n            photo_id   TEXT    NOT NULL,\n            gesture    TEXT    NOT NULL,\n            status     TEXT    DEFAULT 'pending',  -- 'pending' / 'approved' / 'rejected'\n            created_at INTEGER\n        );\n\n        -- ===== СИСТЕМА АРТЕФАКТОВ (ЗНАЧКИ) =====\n        CREATE TABLE IF NOT EXISTS user_badges (\n            tg_id       INTEGER NOT NULL,\n            badge_id    TEXT    NOT NULL,\n            awarded_at  INTEGER NOT NULL,\n            PRIMARY KEY (tg_id, badge_id)\n        );\n\n        CREATE INDEX IF NOT EXISTS idx_badges_user ON user_badges(tg_id);\n        """
    )
    # Миграции: добавляем поля, которых может не быть в старых базах
    migrations = [
        ("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0", "verified"),
        ("ALTER TABLE users ADD COLUMN anon_messages_count INTEGER DEFAULT 0", "anon_messages_count"),
        ("ALTER TABLE likes ADD COLUMN message TEXT", "message"),
    ]
    for sql, col_name in migrations:
        try:
            await db.execute(sql)
            await db.commit()
        except Exception:
            pass  # уже существует
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
    await db.execute("DELETE FROM user_photos WHERE tg_id = ?", (tg_id,))
    await db.execute("DELETE FROM verify_requests WHERE tg_id = ?", (tg_id,))
    await db.execute("DELETE FROM user_badges WHERE tg_id = ?", (tg_id,))  -- NEW
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


async def increment_anon_messages(tg_id: int) -> None:
    """Увеличивает счётчик сообщений в анонимном чате."""
    db = await get_db()
    await db.execute(
        "UPDATE users SET anon_messages_count = anon_messages_count + 1 WHERE tg_id = ?",
        (tg_id,),
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
        f"""\n        SELECT u.* FROM users u\n        WHERE u.tg_id != :me\n          AND u.active = 1\n          AND u.is_banned = 0\n          AND u.age BETWEEN :min_age AND :max_age\n          {gender_clause}\n          AND (u.seeking = 'any' OR u.seeking = :my_gender)\n          AND u.tg_id NOT IN (SELECT to_id FROM likes WHERE from_id = :me)\n        ORDER BY u.last_active DESC, u.shown ASC, RANDOM()\n        LIMIT 1\n        """,
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
        """\n        SELECT u.* FROM likes l\n        JOIN users u ON u.tg_id = l.from_id\n        WHERE l.to_id = ? AND l.is_like = 1\n          AND u.active = 1 AND u.is_banned = 0\n          AND l.from_id NOT IN (\n                SELECT to_id FROM likes WHERE from_id = ? AND is_like = 1\n          )\n        ORDER BY l.created_at DESC\n        """,
        (tg_id, tg_id),
    )
    return await cur.fetchall()


async def count_incoming_likes(tg_id: int) -> int:
    rows = await incoming_likes(tg_id)
    return len(rows)


async def get_matches(tg_id: int) -> list[aiosqlite.Row]:
    db = await get_db()
    cur = await db.execute(
        """\n        SELECT u.* FROM matches m\n        JOIN users u ON u.tg_id = (CASE WHEN m.a_id = ? THEN m.b_id ELSE m.a_id END)\n        WHERE (m.a_id = ? OR m.b_id = ?)\n          AND u.is_banned = 0\n        ORDER BY m.created_at DESC\n        """,
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
    """Подбор собеседника для «Свидания вслепую».\n\n    Возвращает (status, partner_id):\n      'in_session' — уже в активном чате (partner_id — собеседник)\n      'matched'    — нашли собеседника, создана сессия (partner_id)\n      'queued'     — добавлены в очередь ожидания (None)\n      'waiting'    — уже стояли в очереди (None)\n    """
    db = await get_db()
    partner = await anon_active_partner(tg_id)
    if partner is not None:
        return "in_session", partner

    # Ищем ожидающего собеседника (не себя, активного, не забаненного)
    cur = await db.execute(
        """\n        SELECT q.tg_id FROM anon_queue q\n        JOIN users u ON u.tg_id = q.tg_id\n        WHERE q.tg_id != ? AND u.is_banned = 0 AND u.name IS NOT NULL\n        ORDER BY q.created_at ASC LIMIT 1\n        """,
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


# ---------- Фото галерея ----------

async def get_photos(tg_id: int) -> list[aiosqlite.Row]:
    """Все фото пользователя по порядку."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM user_photos WHERE tg_id = ? ORDER BY position", (tg_id,)
    )
    return await cur.fetchall()


async def add_photo(tg_id: int, photo_id: str) -> int:
    """Добавляет фото на следующую позицию. Возвращает position."""
    db = await get_db()
    cur = await db.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM user_photos WHERE tg_id = ?",
        (tg_id,),
    )
    row = await cur.fetchone()
    pos = row["next_pos"]
    now = int(time.time())
    await db.execute(
        "INSERT OR REPLACE INTO user_photos (tg_id, photo_id, position, created_at) VALUES (?, ?, ?, ?)",
        (tg_id, photo_id, pos, now),
    )
    await db.commit()
    return pos


async def remove_photo(tg_id: int, position: int) -> None:
    """Удаляет фото и перенумеровывает остальные."""
    db = await get_db()
    await db.execute(
        "DELETE FROM user_photos WHERE tg_id = ? AND position = ?", (tg_id, position)
    )
    # Перенумеруем
    cur = await db.execute(
        "SELECT photo_id FROM user_photos WHERE tg_id = ? ORDER BY position", (tg_id,)
    )
    rows = await cur.fetchall()
    await db.execute("DELETE FROM user_photos WHERE tg_id = ?", (tg_id,))
    for i, r in enumerate(rows):
        await db.execute(
            "INSERT INTO user_photos (tg_id, photo_id, position, created_at) VALUES (?, ?, ?, ?)",
            (tg_id, r["photo_id"], i, int(time.time())),
        )
    await db.commit()


async def set_main_photo(tg_id: int, photo_id: str) -> None:
    """Обновляет photo_id в users и ставит фото на позицию 0 в user_photos."""
    await upsert_user(tg_id, photo_id=photo_id)


async def sync_photos_to_gallery(tg_id: int) -> None:
    """Если gallery пуста, заполняем из users.photo_id."""
    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*) AS c FROM user_photos WHERE tg_id = ?", (tg_id,)
    )
    row = await cur.fetchone()
    if row["c"] == 0:
        user = await get_user(tg_id)
        if user and user["photo_id"]:
            await add_photo(tg_id, user["photo_id"])


async def photo_count(tg_id: int) -> int:
    db = await get_db()
    cur = await db.execute(
        "SELECT COUNT(*) AS c FROM user_photos WHERE tg_id = ?", (tg_id,)
    )
    row = await cur.fetchone()
    return row["c"] if row else 0


# ---------- Верификация ----------

async def submit_verification(tg_id: int, photo_id: str, gesture: str) -> None:
    db = await get_db()
    now = int(time.time())
    await db.execute(
        "INSERT OR REPLACE INTO verify_requests (tg_id, photo_id, gesture, status, created_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (tg_id, photo_id, gesture, now),
    )
    await db.commit()


async def get_pending_verifications() -> list[aiosqlite.Row]:
    db = await get_db()
    cur = await db.execute(
        "SELECT v.*, u.name, u.username FROM verify_requests v "
        "JOIN users u ON u.tg_id = v.tg_id "
        "WHERE v.status = 'pending' ORDER BY v.created_at"
    )
    return await cur.fetchall()


async def approve_verification(tg_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE verify_requests SET status = 'approved' WHERE tg_id = ?", (tg_id,)
    )
    await db.execute("UPDATE users SET verified = 1 WHERE tg_id = ?", (tg_id,))
    await db.commit()


async def reject_verification(tg_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE verify_requests SET status = 'rejected' WHERE tg_id = ?", (tg_id,)
    )
    await db.commit()


async def get_verification_status(tg_id: int) -> str | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT status FROM verify_requests WHERE tg_id = ? ORDER BY created_at DESC LIMIT 1",
        (tg_id,),
    )
    row = await cur.fetchone()
    return row["status"] if row else None


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


# ---------- Админ-функции ----------

async def admin_extended_stats() -> dict:
    """Расширенная статистика для админ-панели."""
    db = await get_db()
    now = int(time.time())
    today_start = now - (now % 86400)
    out: dict = {}
    for key, q in {
        "new_today": f"SELECT COUNT(*) c FROM users WHERE created_at >= {today_start}",
        "banned": "SELECT COUNT(*) c FROM users WHERE is_banned = 1",
        "reports": "SELECT COUNT(*) c FROM reports",
        "males": "SELECT COUNT(*) c FROM users WHERE gender = 'm'",
        "females": "SELECT COUNT(*) c FROM users WHERE gender = 'f'",
    }.items():
        cur = await db.execute(q)
        row = await cur.fetchone()
        out[key] = row["c"] if row else 0
    return out


async def admin_recent_users(limit: int = 20) -> list[aiosqlite.Row]:
    """Последние зарегистрированные пользователи."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM users WHERE name IS NOT NULL ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return await cur.fetchall()


async def admin_recent_reports(limit: int = 10) -> list[aiosqlite.Row]:
    """Самые свежие жалобы (с подсчётом)."""
    db = await get_db()
    cur = await db.execute(
        """\n        SELECT to_id, COUNT(*) AS report_count, MAX(created_at) AS last_report\n        FROM reports\n        GROUP BY to_id\n        ORDER BY last_report DESC\n        LIMIT ?\n        """,
        (limit,),
    )
    return await cur.fetchall()


async def admin_ban_user(tg_id: int) -> None:
    db = await get_db()
    await db.execute("UPDATE users SET is_banned = 1 WHERE tg_id = ?", (tg_id,))
    await db.commit()


async def admin_unban_user(tg_id: int) -> None:
    db = await get_db()
    await db.execute("UPDATE users SET is_banned = 0 WHERE tg_id = ?", (tg_id,))
    await db.commit()


async def admin_all_active_ids() -> list[int]:
    """Все активные незабаненные пользователи (для рассылки)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT tg_id FROM users WHERE active = 1 AND is_banned = 0 AND name IS NOT NULL"
    )
    rows = await cur.fetchall()
    return [r["tg_id"] for r in rows]


# ---------- Тикеты поддержки ----------

async def create_ticket(tg_id: int, category: str, message: str, photo_id: str | None = None) -> int:
    """Создаёт тикет, возвращает id."""
    db = await get_db()
    now = int(time.time())
    cur = await db.execute(
        "INSERT INTO support_tickets (tg_id, category, message, photo_id, status, created_at) "
        "VALUES (?, ?, ?, ?, 'open', ?)",
        (tg_id, category, message, photo_id, now),
    )
    await db.commit()
    return cur.lastrowid


async def get_tickets(status: str | None = None, limit: int = 50, offset: int = 0) -> list[aiosqlite.Row]:
    db = await get_db()
    if status:
        cur = await db.execute(
            """SELECT t.*, u.name, u.username FROM support_tickets t\n               LEFT JOIN users u ON u.tg_id = t.tg_id\n               WHERE t.status = ?\n               ORDER BY t.created_at DESC LIMIT ? OFFSET ?""",
            (status, limit, offset),
        )
    else:
        cur = await db.execute(
            """SELECT t.*, u.name, u.username FROM support_tickets t\n               LEFT JOIN users u ON u.tg_id = t.tg_id\n               ORDER BY t.created_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )
    return await cur.fetchall()


async def get_ticket(ticket_id: int) -> aiosqlite.Row | None:
    db = await get_db()
    cur = await db.execute(
        """SELECT t.*, u.name, u.username FROM support_tickets t\n           LEFT JOIN users u ON u.tg_id = t.tg_id\n           WHERE t.id = ?""",
        (ticket_id,),
    )
    return await cur.fetchone()


async def reply_ticket(ticket_id: int, reply_text: str) -> None:
    db = await get_db()
    now = int(time.time())
    await db.execute(
        "UPDATE support_tickets SET status = 'replied', admin_reply = ?, replied_at = ? WHERE id = ?",
        (reply_text, now, ticket_id),
    )
    await db.commit()


async def close_ticket(ticket_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE support_tickets SET status = 'closed' WHERE id = ?",
        (ticket_id,),
    )
    await db.commit()


async def delete_ticket(ticket_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM support_tickets WHERE id = ?", (ticket_id,))
    await db.commit()


async def tickets_count(status: str | None = None) -> int:
    db = await get_db()
    if status:
        cur = await db.execute(
            "SELECT COUNT(*) c FROM support_tickets WHERE status = ?", (status,)
        )
    else:
        cur = await db.execute("SELECT COUNT(*) c FROM support_tickets")
    row = await cur.fetchone()
    return row["c"] if row else 0
