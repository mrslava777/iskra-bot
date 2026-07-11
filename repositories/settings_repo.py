"""Settings/Admin repository — операции админ-панели, статистики, жалоб, банов.

FIX (#8): import time наверху.
PERF (пул): чистые чтения помечены db(write=False).
NEW: порог автоскрытия по жалобам (REPORTS_AUTO_HIDE уникальных жалобщиков).
NEW v2: admin_recent_reports отдаёт статус цели (active/is_banned), чтобы админ
 в разделе «Жалобы» сразу видел — анкета уже скрыта/забанена или ещё висит.
"""
import time

from database.connection import db

# Сколько РАЗНЫХ пользователей должны пожаловаться, чтобы анкета авто-скрылась.
REPORTS_AUTO_HIDE = 5


# ── Statistics ────────────────────────────────────────────────────

async def stats() -> dict:
    """Возвращает базовую статистику одним запросом."""
    async with db(write=False) as conn:
        cursor = await conn.execute("""
            SELECT
                COUNT(*) as users,
                SUM(CASE WHEN active = 1 AND is_banned = 0 THEN 1 ELSE 0 END) as active,
                (SELECT COUNT(*) FROM likes WHERE is_like = 1) as likes,
                (SELECT COUNT(*) FROM matches) as matches
            FROM users
        """)
        row = await cursor.fetchone()
        return dict(row)


async def admin_extended_stats() -> dict:
    """Возвращает расширенную статистику для админ-панели одним запросом."""
    async with db(write=False) as conn:
        now = int(time.time())
        today_start = now - (now % 86400)

        cursor = await conn.execute("""
            SELECT
                SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as new_today,
                SUM(CASE WHEN is_banned = 1 THEN 1 ELSE 0 END) as banned,
                (SELECT COUNT(*) FROM reports) as reports,
                SUM(CASE WHEN gender = 'm' THEN 1 ELSE 0 END) as males,
                SUM(CASE WHEN gender = 'f' THEN 1 ELSE 0 END) as females
            FROM users
        """, (today_start,))
        row = await cursor.fetchone()
        return dict(row)


# ── Users management ──────────────────────────────────────────────

async def admin_recent_users(limit: int = 20) -> list:
    """Возвращает последних пользователей."""
    async with db(write=False) as conn:
        cursor = await conn.execute(
            """
            SELECT tg_id, name, username, age, active, is_banned
            FROM users ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def admin_all_active_ids() -> list:
    """Возвращает ID всех активных пользователей."""
    async with db(write=False) as conn:
        cursor = await conn.execute(
            "SELECT tg_id FROM users WHERE active = 1 AND is_banned = 0"
        )
        rows = await cursor.fetchall()
        return [r["tg_id"] for r in rows]


# ── Reports ───────────────────────────────────────────────────────

async def add_report(from_id: int, to_id: int) -> dict:
    """Добавляет жалобу и применяет порог автоскрытия.

    Возвращает {"unique_reporters": N, "auto_hidden": bool}.
    Считаем УНИКАЛЬНЫХ жалобщиков (COUNT(DISTINCT from_id)), чтобы один человек
    не мог снести кого угодно флудом. При >= REPORTS_AUTO_HIDE и ещё видимой
    анкете — скрываем из ленты (active=0). Это не бан. Всё в одной транзакции.
    """
    now = int(time.time())
    async with db() as conn:
        await conn.execute(
            "INSERT INTO reports (from_id, to_id, created_at) VALUES (?, ?, ?)",
            (from_id, to_id, now),
        )

        cur = await conn.execute(
            "SELECT COUNT(DISTINCT from_id) AS c FROM reports WHERE to_id = ?",
            (to_id,),
        )
        row = await cur.fetchone()
        unique_reporters = row["c"] if row else 0

        auto_hidden = False
        if unique_reporters >= REPORTS_AUTO_HIDE:
            cur2 = await conn.execute(
                "SELECT active, is_banned FROM users WHERE tg_id = ?",
                (to_id,),
            )
            u = await cur2.fetchone()
            if u and u["active"] and not u["is_banned"]:
                await conn.execute(
                    "UPDATE users SET active = 0 WHERE tg_id = ?",
                    (to_id,),
                )
                auto_hidden = True

        return {"unique_reporters": unique_reporters, "auto_hidden": auto_hidden}


async def admin_recent_reports(limit: int = 10) -> list:
    """Последние жалобы с уникальными жалобщиками И статусом цели.

    Возвращает список dict: to_id, report_count, active, is_banned.
    Статус нужен, чтобы админ видел, скрыта ли уже анкета (сработал ли порог).
    """
    async with db(write=False) as conn:
        cursor = await conn.execute(
            """
            SELECT
                r.to_id AS to_id,
                COUNT(DISTINCT r.from_id) AS report_count,
                u.active AS active,
                u.is_banned AS is_banned
            FROM reports r
            LEFT JOIN users u ON u.tg_id = r.to_id
            GROUP BY r.to_id
            ORDER BY report_count DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


# ── Ban/Unban ─────────────────────────────────────────────────────

async def admin_ban_user(tg_id: int) -> None:
    """Банит пользователя."""
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET is_banned = 1, active = 0 WHERE tg_id = ?",
            (tg_id,),
        )


async def admin_unban_user(tg_id: int) -> None:
    """Разбанивает пользователя (и возвращает в ленту)."""
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET is_banned = 0, active = 1 WHERE tg_id = ?",
            (tg_id,),
        )
