"""Конфигурация бота Искра."""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv может быть не установлен в проде
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Путь к базе.
# Логика автоопределения, чтобы анкеты сохранялись без ручной настройки:
#   1) если задан DB_PATH в переменных окружения — используем его;
#   2) иначе, если примонтирован Railway Volume в /data (папка существует
#      и доступна на запись) — кладём базу туда -> /data/iskra.db (постоянно);
#   3) иначе локально ./iskra.db (на Railway без Volume это временно).
def _resolve_db_path() -> str:
    explicit = os.getenv("DB_PATH", "").strip()
    if explicit:
        return explicit
    data_dir = "/data"
    try:
        os.makedirs(data_dir, exist_ok=True)
        if os.access(data_dir, os.W_OK):
            return os.path.join(data_dir, "iskra.db")
    except Exception:
        pass
    return "iskra.db"


DB_PATH = _resolve_db_path()

# Постоянное ли хранилище (для понятного лога при старте)
DB_PERSISTENT = os.path.dirname(os.path.abspath(DB_PATH)) == "/data"

# ID администраторов через запятую (для модерации жалоб), напр. "12345,67890"
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
}

# Сколько входящих лайков показывать бесплатно в списке
LIKES_PREVIEW = int(os.getenv("LIKES_PREVIEW", "10"))

if not BOT_TOKEN:
    # Не падаем на импорте — bot.py выдаст понятную ошибку
    pass
