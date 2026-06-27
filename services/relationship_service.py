"""Сервис уровней отношений между мэтчами — только через репозитории."""
from typing import Optional

from data.constants import Relationship, RELATIONSHIP_LEVEL_NAMES, ProgressBar, Format
import repositories.relationship_repo as rel_repo


class RelationshipService:
    """Сервис для работы с уровнями отношений."""

    THRESHOLDS = Relationship.THRESHOLDS

    @staticmethod
    async def ensure_exists(user1_id: int, user2_id: int) -> None:
        await rel_repo.create_relationship(user1_id, user2_id)

    @staticmethod
    async def add_points(user1_id: int, user2_id: int, points: int, reason: str = "") -> None:
        """Добавляет очки и обновляет уровень одной транзакцией.

        Оптимизация: вместо отдельных add_points + _update_level (2-3 запроса)
        используем add_points_with_level_update (1-2 запроса).
        """
        await rel_repo.add_points_with_level_update(user1_id, user2_id, points)


async def get_relationship(user1_id: int, user2_id: int) -> Optional[dict]:
    rel = await rel_repo.get_relationship(user1_id, user2_id)
    if not rel:
        return None
    return await _build_stats(user1_id, user2_id)


async def add_message_event(user1_id: int, user2_id: int) -> None:
    rel = await rel_repo.get_relationship(user1_id, user2_id)
    if not rel:
        return
    await rel_repo.add_points_with_level_update(user1_id, user2_id, 1)


def _calc_level(points: int) -> int:
    """Вычисляет уровень по очкам."""
    new_level = 0
    for i, threshold in enumerate(RelationshipService.THRESHOLDS):
        if points >= threshold:
            new_level = i
    return new_level


async def _build_stats(user1_id: int, user2_id: int) -> dict:
    result = await rel_repo.get_points_and_level(user1_id, user2_id)
    if result is None:
        return {"exists": False}
    points, level = result
    next_threshold = RelationshipService.THRESHOLDS[level + 1] if level < len(RelationshipService.THRESHOLDS) - 1 else 0
    return {
        "exists": True,
        "points": points,
        "level": level,
        "next": next_threshold,
    }


def format_status(rel_stats: dict, viewer_id: int) -> str:
    if not rel_stats or not rel_stats.get("exists"):
        return RELATIONSHIP_LEVEL_NAMES.get(0)

    level = rel_stats["level"]
    points = rel_stats["points"]
    next_threshold = rel_stats["next"]

    level_name = RELATIONSHIP_LEVEL_NAMES.get(level)
    progress = min(100, int(points / next_threshold * 100)) if next_threshold > 0 else 100
    bar = ProgressBar.FILLED * (progress // ProgressBar.SIZE) + ProgressBar.EMPTY * (ProgressBar.SIZE - progress // ProgressBar.SIZE)

    return (
        f"{level_name}\n"
        f"{Format.REL_STATUS_POINTS.format(points, next_threshold)}"
        f"{Format.REL_STATUS_BAR.format(bar, progress)}"
    )
