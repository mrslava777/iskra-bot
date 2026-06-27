"""Конфигурация бота Искра."""
import os
from dotenv import load_dotenv

from data.constants import Broadcast, AnonChat

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Администраторы (список tg_id через запятую)
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip().isdigit()]

# База данных PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "")

# --- Оптимизации под нагрузку ---

# Broadcast: batch + concurrency + rate limit
BROADCAST_BATCH_SIZE = int(os.getenv("BROADCAST_BATCH_SIZE", str(Broadcast.BATCH_SIZE)))
BROADCAST_DELAY = float(os.getenv("BROADCAST_DELAY", str(Broadcast.DELAY)))
BROADCAST_CONCURRENT = int(os.getenv("BROADCAST_CONCURRENT", str(Broadcast.CONCURRENT)))

# Rate limits
ANON_RATE_LIMIT_MSG_PER_MIN = int(os.getenv("ANON_RATE_LIMIT_MSG_PER_MIN", str(AnonChat.RATE_LIMIT_MSG_PER_MIN)))
