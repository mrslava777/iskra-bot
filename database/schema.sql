-- Схема базы данных Искра — SQLite

CREATE TABLE IF NOT EXISTS users (
    tg_id           INTEGER PRIMARY KEY,
    username        TEXT,
    name            TEXT,
    age             INTEGER,
    gender          TEXT,
    seeking         TEXT,
    city            TEXT,
    bio             TEXT,
    interests       TEXT,
    photo_id        TEXT,
    verified        INTEGER DEFAULT 0,
    is_banned       INTEGER DEFAULT 0,
    active          INTEGER DEFAULT 1,
    rating          INTEGER DEFAULT 0,
    streak          INTEGER DEFAULT 0,
    anon_messages_count INTEGER DEFAULT 0,
    max_compat      INTEGER DEFAULT 0,
    created_at      INTEGER,
    last_active     INTEGER
);

CREATE TABLE IF NOT EXISTS likes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id     INTEGER NOT NULL,
    to_id       INTEGER NOT NULL,
    is_like     INTEGER NOT NULL,
    created_at  INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(from_id, to_id)
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id        INTEGER NOT NULL,
    b_id        INTEGER NOT NULL,
    created_at  INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(a_id, b_id)
);

CREATE TABLE IF NOT EXISTS shown_profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id     INTEGER NOT NULL,
    to_id       INTEGER NOT NULL,
    shown_at    INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(from_id, to_id)
);

CREATE TABLE IF NOT EXISTS anon_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id        INTEGER NOT NULL,
    b_id        INTEGER NOT NULL,
    a_reveal    INTEGER DEFAULT 0,
    b_reveal    INTEGER DEFAULT 0,
    started_at  INTEGER DEFAULT (strftime('%s','now')),
    ended_at    INTEGER
);

CREATE TABLE IF NOT EXISTS anon_queue (
    tg_id       INTEGER PRIMARY KEY,
    joined_at   INTEGER DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS user_badges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    badge_id    TEXT NOT NULL,
    awarded_at  INTEGER DEFAULT (strftime('%s','now')),
    UNIQUE(tg_id, badge_id)
);

CREATE TABLE IF NOT EXISTS relationships (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user1_id    INTEGER NOT NULL,
    user2_id    INTEGER NOT NULL,
    points      INTEGER DEFAULT 0,
    level       INTEGER DEFAULT 0,
    UNIQUE(user1_id, user2_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id     INTEGER NOT NULL,
    to_id       INTEGER NOT NULL,
    reason      TEXT,
    created_at  INTEGER DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    category    TEXT,
    message     TEXT,
    status      TEXT DEFAULT 'open',
    created_at  INTEGER DEFAULT (strftime('%s','now')),
    replied_at  INTEGER
);

CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    photo_id    TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(tg_id, position)
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);
CREATE INDEX IF NOT EXISTS idx_users_banned ON users(is_banned);
CREATE INDEX IF NOT EXISTS idx_users_photo ON users(photo_id);
CREATE INDEX IF NOT EXISTS idx_likes_from_to ON likes(from_id, to_id);
CREATE INDEX IF NOT EXISTS idx_likes_to ON likes(to_id, is_like);
CREATE INDEX IF NOT EXISTS idx_matches_a ON matches(a_id, b_id);
CREATE INDEX IF NOT EXISTS idx_matches_b ON matches(b_id);
CREATE INDEX IF NOT EXISTS idx_shown_from ON shown_profiles(from_id, to_id);
CREATE INDEX IF NOT EXISTS idx_shown_at ON shown_profiles(from_id, shown_at);
CREATE INDEX IF NOT EXISTS idx_anon_a ON anon_sessions(a_id, ended_at);
CREATE INDEX IF NOT EXISTS idx_anon_b ON anon_sessions(b_id, ended_at);
CREATE INDEX IF NOT EXISTS idx_badges_user ON user_badges(tg_id, badge_id);
CREATE INDEX IF NOT EXISTS idx_rel_users ON relationships(user1_id, user2_id);
CREATE INDEX IF NOT EXISTS idx_reports_from ON reports(from_id);
CREATE INDEX IF NOT EXISTS idx_reports_to ON reports(to_id);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(tg_id, status);
CREATE INDEX IF NOT EXISTS idx_photos_user ON photos(tg_id, position);
