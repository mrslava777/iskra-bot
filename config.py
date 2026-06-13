"""Конфигурация бота Искра."""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv может быть не установлен в проде
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Путь к базе. На Railway удобно монтировать volume в /data
DB_PATH = os.getenv("DB_PATH", "iskra.db").strip()

# ID администраторов через запятую (для модерации жалоб), напр. "12345,67890"
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
}

# Сколько входящих лайков показывать бесплатно в списке
LIKES_PREVIEW = int(os.getenv("LIKES_PREVIEW", "10"))

if not BOT_TOKEN:
    # Не падаем на импорте — bot.py выдаст понятную ошибку
    pass
