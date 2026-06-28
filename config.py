*** Begin Patch
*** Update File: config.py
@@
-DATABASE_URL = os.getenv("DATABASE_URL", "")
+DATABASE_URL = os.getenv("DATABASE_URL", "")
+PGBOUNCER_URL = os.getenv("PGBOUNCER_URL", "")
+DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
+DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))
+
+# Redis
+REDIS_URL = os.getenv("REDIS_URL", "")
@@
 MAX_TRACKED_USERS = int(os.getenv("MAX_TRACKED_USERS", "10000"))
@@
 SENTRY_DSN = os.getenv("SENTRY_DSN", "")
+
+# Send queue / workers
+SEND_CONCURRENCY = int(os.getenv("SEND_CONCURRENCY", "20"))
+NUM_WORKERS = int(os.getenv("NUM_WORKERS", "4"))
+MAX_MESSAGE_RATE_GLOBAL = int(os.getenv("MAX_MESSAGE_RATE_GLOBAL", "20"))
*** End Patch
