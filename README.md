# Искра — Telegram-бот знакомств

Чистая модульная архитектура: тонкие хендлеры → сервисы (бизнес-логика) → репозитории (доступ к БД).

## Структура

```
main.py                 — точка входа (polling + health-сервер)
config.py               — конфигурация из переменных окружения
health.py               — health-check сервер (для Railway)
keyboards.py            — клавиатуры (inline / reply)
states.py               — FSM-состояния
badges.py               — определения артефактов (значков)

data/
  constants.py          — все строки, эмодзи, пороги (без «магических чисел»)
  enums.py              — типизированные enum-значения вместо строк
  content.py            — интересы, вопросы дня, ледоколы

database/
  connection.py         — пул соединений aiosqlite + инициализация схемы
  schema.py             — документация схемы

repositories/           — слой доступа к данным (по таблице/домену)
services/               — бизнес-логика (совместимость, значки, уведомления, …)
handlers/               — обработчики Telegram, сгруппированы по доменам
  start, matching/, profile/, anon/, badges, support/, admin/, misc
```

Доступ к БД:
- `get_db()` — общее долгоживущее соединение для чтения;
- `get_single_db()` — отдельное соединение на запись (вызывающий закрывает сам);
- `close_db_pool()` — graceful shutdown.

## Запуск локально

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN=...        # токен бота
export ADMIN_IDS=123,456    # id админов через запятую
export DB_PATH=./iskra.db   # путь к SQLite (по умолчанию /data/iskra.db)
python main.py
```

## Деплой (Railway)

`Procfile` и `railway.json` запускают `python main.py`. Для постоянного
хранения БД смонтируйте Volume в `/data` (тогда используется `/data/iskra.db`).

## Переменные окружения

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | токен Telegram-бота | — (обязательно) |
| `ADMIN_IDS` | id админов через запятую | пусто |
| `DB_PATH` | путь к файлу SQLite | `/data/iskra.db` |
| `BROADCAST_BATCH_SIZE` / `BROADCAST_DELAY` / `BROADCAST_CONCURRENT` | параметры рассылки | см. `data/constants.py` |
| `ANON_RATE_LIMIT_MSG_PER_MIN` | лимит сообщений в анон-чате | см. `data/constants.py` |
