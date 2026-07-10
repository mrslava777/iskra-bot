-- Migration: Add NSFW moderation tables and columns
-- Created: 2026-07-10

-- Add nsfw_strikes to users if not exists (SQLite workaround)
-- Note: SQLite doesn't support IF NOT EXISTS for ALTER COLUMN
-- We'll create a new table and migrate if needed, or just handle in code

-- For now, the column is handled gracefully in code with COALESCE
-- CREATE TABLE IF NOT EXISTS users already has all columns in schema.sql

-- If upgrading existing DB, run this:
-- PRAGMA foreign_keys=off;
-- BEGIN TRANSACTION;
-- ALTER TABLE users ADD COLUMN nsfw_strikes INTEGER DEFAULT 0;
-- COMMIT;
-- PRAGMA foreign_keys=on;
