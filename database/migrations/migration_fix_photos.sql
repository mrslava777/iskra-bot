-- Migration: Fix photo saving issues
-- Run this to fix "фото не удалось сохранить" errors
-- Date: 2026-07-10

-- ============================================
-- STEP 1: Recreate photos table with proper constraints
-- ============================================

-- Backup existing photos
CREATE TABLE IF NOT EXISTS photos_backup AS SELECT * FROM photos;

-- Drop old photos table (if exists without proper constraints)
DROP TABLE IF EXISTS photos;

-- Create new photos table with proper constraints
CREATE TABLE photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    photo_id TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(tg_id, position)
);

-- Restore data from backup (keep newest for each position)
INSERT INTO photos (tg_id, photo_id, position, created_at)
SELECT tg_id, photo_id, position, created_at
FROM photos_backup p1
WHERE id IN (
    SELECT MAX(id)
    FROM photos_backup p2
    GROUP BY p2.tg_id, p2.position
)
OR created_at IS NULL;

-- Drop backup
DROP TABLE IF EXISTS photos_backup;

-- Create indexes
CREATE INDEX idx_photos_tg_id ON photos(tg_id);
CREATE INDEX idx_photos_tg_pos ON photos(tg_id, position);

-- ============================================
-- STEP 2: Ensure users.photo_id is synced with photos.position=0
-- ============================================

-- For users with photo_id but no gallery entry
INSERT INTO photos (tg_id, photo_id, position)
SELECT tg_id, photo_id, 0
FROM users
WHERE photo_id IS NOT NULL
  AND tg_id NOT IN (SELECT tg_id FROM photos WHERE position = 0)
ON CONFLICT (tg_id, position) DO UPDATE SET
    photo_id = excluded.photo_id;

-- ============================================
-- STEP 3: Add missing columns to users if needed
-- ============================================

-- nsfw_strikes column (for NSFW moderation)
ALTER TABLE users ADD COLUMN nsfw_strikes INTEGER DEFAULT 0;

-- max_compat column (for compatibility tracking)
ALTER TABLE users ADD COLUMN max_compat INTEGER DEFAULT 0;

-- anon_messages_count column (for anonymous chat stats)
ALTER TABLE users ADD COLUMN anon_messages_count INTEGER DEFAULT 0;

-- ============================================
-- STEP 4: Create NSFW moderation tables
-- ============================================

CREATE TABLE IF NOT EXISTS nsfw_banned_hashes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_hash TEXT UNIQUE NOT NULL,
    reason TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS nsfw_review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    message_id INTEGER,
    chat_id INTEGER,
    ai_score REAL,
    status TEXT DEFAULT 'pending',
    reviewed_by INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    reviewed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_nsfw_hash ON nsfw_banned_hashes(image_hash);
CREATE INDEX IF NOT EXISTS idx_nsfw_review_status ON nsfw_review_queue(status);
CREATE INDEX IF NOT EXISTS idx_nsfw_review_user ON nsfw_review_queue(tg_id);

-- ============================================
-- STEP 5: Create tickets table if missing
-- ============================================

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    text TEXT NOT NULL,
    photo_id TEXT,
    reply TEXT,
    status TEXT DEFAULT 'open',
    created_at INTEGER DEFAULT (strftime('%s','now')),
    updated_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tickets_tg_id ON tickets(tg_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

-- ============================================
-- STEP 6: Create user_badges table if missing
-- ============================================

CREATE TABLE IF NOT EXISTS user_badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    badge_id TEXT NOT NULL,
    awarded_at INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(tg_id, badge_id)
);

CREATE INDEX IF NOT EXISTS idx_user_badges_tg_id ON user_badges(tg_id);
CREATE INDEX IF NOT EXISTS idx_user_badges_badge ON user_badges(badge_id);

-- ============================================
-- STEP 7: Verify and cleanup
-- ============================================

-- Remove duplicate photos keeping newest
DELETE FROM photos
WHERE id NOT IN (
    SELECT MAX(id)
    FROM photos
    GROUP BY tg_id, position
);

-- Ensure no position exceeds MAX_EXTRA (4)
DELETE FROM photos WHERE position > 4;

VACUUM;
