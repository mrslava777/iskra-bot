"""Settings/Admin repository — операции админ-панели, статистики, жалоб, банов."""
from database.connection import db


# ── Statistics ────────────────────────────────────────────────────

async def stats() -> dict:
    """Возвращает базовую статистику одним запросом."""
    async with db() as conn:
        row = await conn.fetchrow("""
            SELECT 
                COUNT(*) as users,
                SUM(CASE WHEN active = 1 AND is_banned = 0 THEN 1 ELSE 0 END) as active,
                (SELECT COUNT(*) FROM likes WHERE is_like = 1) as likes,
                (SELECT COUNT(*) FROM matches) as matches
            FROM users
        """)
        return dict(row)


async def admin_extended_stats() -> dict:
    """Возвращает расширенную статистику для админ-панели одним запросом."""
    import time
    async with db() as conn:
        now = int(time.time())
        today_start = now - (now % 86400)

        row = await conn.fetchrow("""
            SELECT 
                SUM(CASE WHEN created_at >= $1 THEN 1 ELSE 0 END) as new_today,
                SUM(CASE WHEN is_banned = 1 THEN 1 ELSE 0 END) as banned,
                (SELECT COUNT(*) FROM reports) as reports,
                SUM(CASE WHEN gender = 'm' THEN 1 ELSE 0 END) as males,
                SUM(CASE WHEN gender = 'f' THEN 1 ELSE 0 END) as females
            FROM users
        """, today_start)
        return dict(row)


# ── Users management ──────────────────────────────────────────────

async def admin_recent_users(limit: int = 20) -> list:
    """Возвращает последних пользователей."""
    async with db() as conn:
        rows = await conn.fetch(
            """
            SELECT tg_id, name, username, age, active, is_banned
            FROM users ORDER BY created_at DESC LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]


async def admin_all_active_ids() -> list:
    """Возвращает ID всех активных пользователей."""
    async with db() as conn:
        rows = await conn.fetch(
            "SELECT tg_id FROM users WHERE active = 1 AND is_banned = 0"
        )
        return [r["tg_id"] for r in rows]


# ── Reports ───────────────────────────────────────────────────────

async def add_report(from_id: int, to_id: int) -> None:
    """Добавляет жалобу."""
    async with db() as conn:
        await conn.execute(
            """
            INSERT INTO reports (from_id, to_id, created_at)
            VALUES ($1, $2, EXTRACT(EPOCH FROM NOW())::INTEGER)
            """,
            from_id, to_id,
        )


async def admin_recent_reports(limit: int = 10) -> list:
    """Возвращает последние жалобы."""
    async with db() as conn:
        rows = await conn.fetch(
            """
            SELECT to_id, COUNT(*) as report_count
            FROM reports
            GROUP BY to_id
            ORDER BY report_count DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]


# ── Ban/Unban ─────────────────────────────────────────────────────

async def admin_ban_user(tg_id: int) -> None:
    """Банит пользователя."""
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET is_banned = 1, active = 0 WHERE tg_id = $1",
            tg_id,
        )


async def admin_unban_user(tg_id: int) -> None:
    """Разбанивает пользователя."""
    async with db() as conn:
        await conn.execute(
            "UPDATE users SET is_banned = 0 WHERE tg_id = $1",
            tg_id,
        )
