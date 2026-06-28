*** Begin Patch
*** Update File: config.py
@@
 # Rate limits
-ANON_RATE_LIMIT_MSG_PER_MIN = int(os.getenv("ANON_RATE_LIMIT_MSG_PER_MIN", str(AnonChat.RATE_LIMIT_MSG_PER_MIN)))
+ANON_RATE_LIMIT_MSG_PER_MIN = int(os.getenv("ANON_RATE_LIMIT_MSG_PER_MIN", str(AnonChat.RATE_LIMIT_MSG_PER_MIN)))
+
+# Параметры для защиты in-memory хранилищ / retry/backoff
+MAX_TRACKED_USERS = int(os.getenv("MAX_TRACKED_USERS", "10000"))
+
+# Параметры для инициализации схемы (переопределяются через env)
+SCHEMA_INIT_RETRIES = int(os.getenv("SCHEMA_INIT_RETRIES", "5"))
+SCHEMA_BACKOFF_BASE = float(os.getenv("SCHEMA_BACKOFF_BASE", "0.5"))
+SCHEMA_BACKOFF_MULT = float(os.getenv("SCHEMA_BACKOFF_MULT", "2"))
+
+# Sentry
+SENTRY_DSN = os.getenv("SENTRY_DSN", "")
*** End Patch
