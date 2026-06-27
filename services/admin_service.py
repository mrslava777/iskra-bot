"""Сервис администрирования — единая точка проверки прав."""
from config import ADMIN_IDS


def is_admin(tg_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return tg_id in ADMIN_IDS
