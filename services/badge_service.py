"""Бизнес-логика проверки и выдачи значков — только через репозитории."""
import time

from badges import BADGES, BADGE_BY_ID
import repositories.anon_repo as anon_repo
import repositories.badge_repo as badge_repo
import repositories.photo_repo as photo_repo
import repositories.user_repo as user_repo


async def check_and_award(tg_id: int) -> list[dict]:
    """Проверяет все значки для пользователя и выдаёт новые."""
    user = await user_repo.get_user(tg_id)
    if not user:
        return []

    stats = await _collect_stats(tg_id, user)
    existing = await badge_repo.get_user_badge_ids(tg_id)

    new_badges = []
    for badge in BADGES:
        if badge["id"] in existing:
            continue
        if badge["condition"](user, stats):
            await badge_repo.award_badge(tg_id, badge["id"], int(time.time()))
            new_badges.append(badge)

    return new_badges


async def _collect_stats(tg_id: int, user: dict) -> dict:
    """Собирает статистику через репозитории.

    Оптимизация: используем batch-запрос get_user_stats() вместо 5 отдельных.
    """
    batch = await badge_repo.get_user_stats(tg_id)
    return {
        "matches": batch["matches"],
        "likes_sent": batch["likes_sent"],
        "anon_messages": user.get("anon_messages_count", 0),
        "photo_count": await photo_repo.photo_count(tg_id),
        "reports_sent": batch["reports_sent"],
        "msglikes": batch["msglikes"],
        "anon_reveals": await anon_repo.anon_reveal_count(tg_id),
        "max_compat": user.get("max_compat", 0) or 0,
    }


async def get_user_badges(tg_id: int) -> list[dict]:
    """Возвращает полные данные о значках пользователя."""
    badge_ids = await badge_repo.get_user_badge_ids(tg_id)
    return [BADGE_BY_ID[bid] for bid in badge_ids if bid in BADGE_BY_ID]


async def get_user_stats(tg_id: int) -> tuple[dict, dict]:
    """Возвращает (user_row, stats_dict) для отображения прогресса.

    Оптимизация: единая точка сбора данных — используется и для check_and_award,
    и для отображения прогресса в UI.
    """
    user = await user_repo.get_user(tg_id)
    if not user:
        return {}, {}
    stats = await _collect_stats(tg_id, user)
    return user, stats
