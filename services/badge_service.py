"""Бизнес-логика проверки и выдачи значков — только через репозитории.

FIX: _collect_stats параллелизирует независимые запросы через asyncio.gather.
FIX: check_and_award кэширует результат на 5 сек, чтобы не гонять тяжёлые
     запросы при каждом свайпе/клике (вызывается из 6+ точек).
FIX v5: get_user_stats принимает предзагруженного user — убирает лишний запрос.
FIX v8: TTL cache уменьшен с 30 → 5 сек для более быстрого обнаружения новых значков.
        Добавлена invalidate_award_cache() для ручного сброса кэша.
"""
import asyncio
import time

from badges import BADGES, BADGE_BY_ID
import repositories.anon_repo as anon_repo
import repositories.badge_repo as badge_repo
import repositories.photo_repo as photo_repo
import repositories.user_repo as user_repo

# Кэш недавних проверок: {tg_id: (result_badges, timestamp)}
# Предотвращает тяжёлые повторные проверки при быстрых действиях
_award_cache: dict[int, tuple[list[dict], float]] = {}
_AWARD_CACHE_TTL = 5  # секунд (FIX v8: уменьшено с 30 для быстрого обнаружения)
_AWARD_CACHE_MAX = 500


def invalidate_award_cache(tg_id: int | None = None) -> None:
    """Сбрасывает кэш выдачи значков.

    FIX v8: публичная функция для ручного сброса кэша.
    Если tg_id не указан — сбрасывает весь кэш.
    """
    global _award_cache
    if tg_id is None:
        _award_cache.clear()
    else:
        _award_cache.pop(tg_id, None)


async def check_and_award(tg_id: int) -> list[dict]:
    """Проверяет все значки для пользователя и выдаёт новые.

    FIX v8: TTL-кэш 5 сек — при множественных вызовах за короткий период
    (свайп → лайк → мэтч → уведомление) повторная проверка пропускается.
    """
    now = time.monotonic()

    # Проверяем кэш — если проверяли недавно, пропускаем
    cached = _award_cache.get(tg_id)
    if cached is not None:
        _, cached_at = cached
        if now - cached_at < _AWARD_CACHE_TTL:
            return []  # Недавно проверяли — нечего выдавать повторно

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

    # Обновляем кэш
    _award_cache[tg_id] = (new_badges, now)
    if len(_award_cache) > _AWARD_CACHE_MAX:
        # Вытесняем самую старую запись
        oldest = min(_award_cache, key=lambda k: _award_cache[k][1])
        del _award_cache[oldest]

    return new_badges


async def _collect_stats(tg_id: int, user: dict) -> dict:
    """Собирает статистику через репозитории.

    FIX: параллелизация через asyncio.gather — вместо 3 последовательных
    запросов (batch_stats, photo_count, anon_reveals) запускаем их одновременно.
    """
    batch_task = badge_repo.get_user_stats(tg_id)
    photo_task = photo_repo.photo_count(tg_id)
    reveals_task = anon_repo.anon_reveal_count(tg_id)

    batch, photos, reveals = await asyncio.gather(
        batch_task, photo_task, reveals_task,
    )

    return {
        "matches": batch["matches"],
        "likes_sent": batch["likes_sent"],
        "anon_messages": user.get("anon_messages_count", 0),
        "photo_count": photos,
        "reports_sent": batch["reports_sent"],
        "msglikes": batch["msglikes"],
        "anon_reveals": reveals,
        "max_compat": user.get("max_compat", 0) or 0,
    }


async def get_user_badges(tg_id: int) -> list[dict]:
    """Возвращает полные данные о значках пользователя."""
    badge_ids = await badge_repo.get_user_badge_ids(tg_id)
    return [BADGE_BY_ID[bid] for bid in badge_ids if bid in BADGE_BY_ID]


async def get_user_badges_batch(tg_ids: list[int]) -> dict[int, list[dict]]:
    """Возвращает значки для нескольких пользователей одним запросом.

    Оптимизация: batch-загрузка вместо N+1.
    """
    badge_map = await badge_repo.get_user_badge_ids_batch(tg_ids)
    result: dict[int, list[dict]] = {}
    for uid, badge_ids in badge_map.items():
        result[uid] = [BADGE_BY_ID[bid] for bid in badge_ids if bid in BADGE_BY_ID]
    # Users with no badges get empty list
    for uid in tg_ids:
        if uid not in result:
            result[uid] = []
    return result


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


# FIX v5: принимает уже загруженного user — убирает лишний get_user()
async def get_user_stats_with_user(user: dict) -> tuple[dict, dict]:
    """Версия get_user_stats для случаев, когда user уже загружен.

    Экономит 1 DB round-trip (~50-150 мс).
    """
    if not user:
        return {}, {}
    stats = await _collect_stats(user["tg_id"], user)
    return user, stats
