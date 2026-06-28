*** Begin Patch
*** Update File: main.py
@@
-import asyncio
-import logging
-import os
-
-from aiohttp import web
-from aiogram import Bot, Dispatcher
-from aiogram.client.default import DefaultBotProperties
-from aiogram.enums import ParseMode
-
-from config import BOT_TOKEN
-from database.connection import close_db_pool, _get_pool, _ensure_schema
-from handlers import setup_routers
+import asyncio
+import logging
+import os
+
+from aiohttp import web
+from aiogram import Bot, Dispatcher
+from aiogram.client.default import DefaultBotProperties
+from aiogram.enums import ParseMode
+
+from config import BOT_TOKEN, SENTRY_DSN
+from database.connection import close_db_pool, _get_pool, _ensure_schema, wait_until_db_ready
+from handlers import setup_routers
+from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
@@
 async def _start_health_server() -> web.AppRunner:
@@
-    app = web.Application()
-    app.router.add_get("/health", _health_handler)
-    app.router.add_get("/ready", _health_handler)
-    app.router.add_get("/", _health_handler)
+    app = web.Application()
+    app.router.add_get("/health", _health_handler)
+    app.router.add_get("/ready", _health_handler)
+    app.router.add_get("/", _health_handler)
+    app.router.add_get("/metrics", _metrics_handler)
     runner = web.AppRunner(app, access_log=None)
     await runner.setup()
     site = web.TCPSite(runner, "0.0.0.0", PORT)
     await site.start()
     log.info("Health-check сервер запущен на порту %s", PORT)
     return runner
@@
 async def on_startup(bot: Bot) -> None:
@@
-    # Прогрев пула — создаём соединения заранее, а не на первом запросе
-    try:
-        pool = await _get_pool()
-        await _ensure_schema(pool)
-        log.info("DB пул прогрет и схема готова")
-    except Exception as e:
-        log.error("Ошибка прогрева DB: %s", e)
+    # Ждём, пока схема прогреется (retry/backoff handled in connection.wait_until_db_ready)
+    try:
+        await wait_until_db_ready(timeout=60)
+        log.info("DB ready (wait_until_db_ready succeeded)")
+    except Exception as e:
+        log.error("DB not ready after wait_until_db_ready: %s", e)
@@
 async def main() -> None:
-    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
+    # Инициализируем Sentry (если задан SENTRY_DSN)
+    if SENTRY_DSN:
+        try:
+            import sentry_sdk
+
+            sentry_sdk.init(SENTRY_DSN, traces_sample_rate=0.0)
+            log.info("Sentry initialized")
+        except Exception as e:
+            log.warning("Failed to init Sentry: %s", e)
+
+    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
     dp = Dispatcher()
@@
     try:
         # Запускаем polling — основной цикл
         log.info("Запускаю бота в режиме long polling...")
         await dp.start_polling(
             bot,
             allowed_updates=dp.resolve_used_update_types(),
             close_bot_session=True,
         )
     finally:
         await health_runner.cleanup()
         log.info("Health-check сервер остановлен")
+
+
+async def _metrics_handler(request: web.Request) -> web.Response:
+    try:
+        data = generate_latest()
+        return web.Response(body=data, content_type=CONTENT_TYPE_LATEST)
+    except Exception as e:
+        log.exception("Failed to generate metrics: %s", e)
+        return web.Response(status=500, text="error")
*** End Patch
