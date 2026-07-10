-- Migration: Fix photo saving issues (SAFE / IDEMPOTENT rewrite)
-- Date: 2026-07-10
--
-- ВАЖНО: schema.sql уже создаёт ВСЕ таблицы и колонки идемпотентно
-- (photos с created_at, users.nsfw_strikes/max_compat/anon_messages_count,
--  nsfw_*, tickets, user_badges). Поэтому старая версия этой миграции
-- была не только лишней, но и ломала запуск:
--   1) DROP TABLE photos + INSERT ... SELECT created_at FROM photos_backup
--      падал с "no such column: created_at", если на волюме остался старый
--      photos_backup без created_at (CREATE TABLE IF NOT EXISTS его не пересоздаёт);
--   2) ALTER TABLE users ADD COLUMN ... дублировал уже существующие колонки
--      → "duplicate column name".
-- Любая из этих ошибок обрывала executescript, миграция не помечалась
-- применённой, и wait_until_db_ready гонял её по кругу бесконечно.
--
-- Эта версия НЕ пересоздаёт photos и НЕ трогает схему users. Она только
-- убирает мусор от прошлых недобегов и безопасно синхронизирует главное фото.

-- Убираем застрявший backup от старой сломанной миграции (мог быть без created_at)
DROP TABLE IF EXISTS photos_backup;

-- Синхронизируем users.photo_id -> photos(position=0). Идемпотентно.
INSERT INTO photos (tg_id, photo_id, position)
SELECT tg_id, photo_id, 0
FROM users
WHERE photo_id IS NOT NULL
  AND tg_id NOT IN (SELECT tg_id FROM photos WHERE position = 0)
ON CONFLICT (tg_id, position) DO UPDATE SET
    photo_id = excluded.photo_id;

-- Чистим возможные дубли по (tg_id, position), оставляя самую свежую запись
DELETE FROM photos
WHERE id NOT IN (
    SELECT MAX(id) FROM photos GROUP BY tg_id, position
);

-- Позиции не должны превышать MAX_EXTRA (4)
DELETE FROM photos WHERE position > 4;
