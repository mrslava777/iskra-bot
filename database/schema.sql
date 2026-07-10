-- Schema for Искра bot
-- Includes all fixes for photo saving issues

-- ============================================
-- USERS
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    age INTEGER,
    gender TEXT,
    seeking TEXT DEFAULT 'any',
    city TEXT,
    bio TEXT,
    interests TEXT,
    photo_id TEXT,
    active INTEGER DEFAULT 1,
    verified INTEGER DEFAULT 0,
    is_banned INTEGER DEFAULT 0,
    daily_q INTEGER DEFAULT 0,
    daily_a TEXT DEFAULT '',
    min_age INTEGER DEFAULT 18,
    max_age INTEGER DEFAULT 99,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    last_active INTEGER DEFAULT (strftime('%s','now')),
    streak INTEGER DEFAULT 0,
    rating INTEGER DEFAULT 0,
    anon_messages_count INTEGER DEFAULT 0,
    max_compat INTEGER DEFAULT 0,
    nsfw_strikes INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);
CREATE INDEX IF NOT EXISTS idx_users_banned ON users(is_banned);
CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active);

-- ============================================
-- PHOTOS (FIXED: proper UNIQUE constraint)
-- ============================================
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    photo_id TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(tg_id, position)
);

CREATE INDEX IF NOT EXISTS idx_photos_tg_id ON photos(tg_id);
CREATE INDEX IF NOT EXISTS idx_photos_tg_pos ON photos(tg_id, position);

-- ============================================
-- LIKES
-- ============================================
CREATE TABLE IF NOT EXISTS likes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    is_like INTEGER DEFAULT 1,
    message TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(from_id, to_id)
);

CREATE INDEX IF NOT EXISTS idx_likes_from ON likes(from_id);
CREATE INDEX IF NOT EXISTS idx_likes_to ON likes(to_id);

-- ============================================
-- MATCHES
-- ============================================
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id INTEGER NOT NULL,
    b_id INTEGER NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(a_id, b_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_a ON matches(a_id);
CREATE INDEX IF NOT EXISTS idx_matches_b ON matches(b_id);

-- ============================================
-- SHOWN PROFILES
-- ============================================
CREATE TABLE IF NOT EXISTS shown_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    shown_at INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(from_id, to_id)
);

CREATE INDEX IF NOT EXISTS idx_shown_from ON shown_profiles(from_id);
CREATE INDEX IF NOT EXISTS idx_shown_to ON shown_profiles(to_id);

-- ============================================
-- REPORTS
-- ============================================
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s','now'))
);

CREATE INDEX IF NOT EXISTS idx_reports_to ON reports(to_id);

-- ============================================
-- ANON QUEUE
-- ============================================
CREATE TABLE IF NOT EXISTS anon_queue (
    tg_id INTEGER PRIMARY KEY,
    queued_at INTEGER DEFAULT (strftime('%s','now'))
);

-- ============================================
-- ANON SESSIONS
-- ============================================
CREATE TABLE IF NOT EXISTS anon_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id INTEGER NOT NULL,
    b_id INTEGER NOT NULL,
    a_reveal INTEGER DEFAULT 0,
    b_reveal INTEGER DEFAULT 0,
    started_at INTEGER DEFAULT (strftime('%s','now')),
    ended_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_anon_a ON anon_sessions(a_id, ended_at);
CREATE INDEX IF NOT EXISTS idx_anon_b ON anon_sessions(b_id, ended_at);

-- ============================================
-- RELATIONSHIPS
-- ============================================
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user1_id INTEGER NOT NULL,
    user2_id INTEGER NOT NULL,
    points INTEGER DEFAULT 0,
    level INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(user1_id, user2_id)
);

-- ============================================
-- TICKETS
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
-- USER BADGES
-- ============================================
CREATE TABLE IF NOT EXISTS user_badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    badge_id TEXT NOT NULL,
    awarded_at INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(tg_id, badge_id)
);

CREATE INDEX IF NOT EXISTS idx_user_badges_tg ON user_badges(tg_id);
CREATE INDEX IF NOT EXISTS idx_user_badges_badge ON user_badges(badge_id);

-- ============================================
-- NSFW MODERATION
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
