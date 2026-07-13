# Искра — Telegram-бот знакомств

Чистая модульная архитектура: тонкие хендлеры → сервисы (бизнес-логика) → репозитории (доступ к БД).

## Структура

```
main.py                 — точка входа (Telegram webhook + health-сервер)
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
- `db()` — контекстный менеджер с пулом SQLite-соединений;
- `get_single_db()` / `release_db()` — совместимый парный API;
- `close_db_pool()` — корректное закрытие при остановке.

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

`Procfile` и `railway.json` запускают `python main.py`.

> **Важно:** SQLite-файл не сохраняется между развёртываниями без Railway Volume.
> Создайте Volume, смонтируйте его в `/data` и задайте `DB_PATH=/data/iskra.db`.
> Оставьте для этого сервиса **одну реплику**: SQLite не рассчитан на одновременную
> работу нескольких экземпляров приложения. Volume не заменяет резервные копии.

1. В **Settings → Networking** создайте **Public Domain** для сервиса.
2. В **Variables** задайте `BOT_TOKEN`, `ADMIN_IDS`, `DB_PATH` и
   `WEBHOOK_SECRET_TOKEN`. Секрет должен состоять только из латинских букв,
   цифр, `_` и `-` (8–256 символов), без кавычек и пробелов.
3. `WEBHOOK_URL` можно не задавать: бот автоматически использует
   `RAILWAY_PUBLIC_DOMAIN`. Если задаёте его вручную, укажите полный HTTPS URL,
   например `https://my-bot.up.railway.app`, без `/webhook` на конце.

После redeploy в логах должна появиться строка `Webhook registered at ...`.
Не копируйте секрет в логи или чат.

## Переменные окружения

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | токен Telegram-бота | — (обязательно) |
| `ADMIN_IDS` | id админов через запятую | пусто |
| `DB_PATH` | путь к файлу SQLite | `database.db` (на Railway: `/data/iskra.db`) |
| `WEBHOOK_URL` | публичный HTTPS URL (не нужен при `RAILWAY_PUBLIC_DOMAIN`) | — |
| `WEBHOOK_SECRET_TOKEN` | постоянный секрет Telegram webhook, 8–256 безопасных символов | временный при отсутствии |
| `DB_POOL_SIZE` | число соединений SQLite, 1–32 | `8` |
| `BROADCAST_BATCH_SIZE` / `BROADCAST_DELAY` / `BROADCAST_CONCURRENT` | параметры рассылки | см. `data/constants.py` |
| `ANON_RATE_LIMIT_MSG_PER_MIN` | лимит сообщений в анон-чате | см. `data/constants.py` |
