"""Схема базы данных Искра — SQLite.

Индексы:
  - users: по active, is_banned, photo_id (для ленты)
  - likes: по from_id+to_id (уникальный), to_id+is_like (входящие)
  - matches: по a_id+b_id (уникальный), a_id, b_id
  - shown_profiles: по from_id+to_id (уникальный), from_id+shown_at
  - anon_sessions: по a_id/b_id + ended_at (активные сессии)
  - anon_queue: по tg_id (уникальный)
  - user_badges: по tg_id+badge_id (уникальный)
  - relationships: по user1_id+user2_id (уникальный)
  - reports: по from_id, to_id
  - tickets: по tg_id+status
  - photos: по tg_id+position (уникальный)
"""

-- ============================================================
-- ПОЛЬЗОВАТЕЛИ
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    tg_id              INTEGER PRIMARY KEY,
    username           TEXT,
    name               TEXT,
    age                INTEGER CHECK (age BETWEEN 14 AND 99),
    gender             TEXT CHECK (gender IN ('m', 'f')),
    seeking            TEXT CHECK (seeking IN ('m', 'f', 'any')),
    city               TEXT,
    bio                TEXT,
    interests          TEXT,  -- CSV индексов: "0,3,7"
    photo_id           TEXT,
    active             INTEGER DEFAULT 1,
    verified           INTEGER DEFAULT 0,
    is_banned          INTEGER DEFAULT 0,
    min_age            INTEGER DEFAULT 18,
    max_age            INTEGER DEFAULT 99,
    daily_q            INTEGER DEFAULT 0,
    daily_a            TEXT DEFAULT '',
    streak             INTEGER DEFAULT 0,
    rating             INTEGER DEFAULT 0,
    max_compat         INTEGER DEFAULT 0,
    anon_messages_count INTEGER DEFAULT 0,
    created_at         INTEGER NOT NULL,
    last_active        INTEGER NOT NULL
);

-- Индексы для users
CREATE INDEX IF NOT EXISTS idx_users_active_banned_photo ON users(active, is_banned, photo_id) WHERE active = 1 AND is_banned = 0 AND photo_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active DESC);
CREATE INDEX IF NOT EXISTS idx_users_gender ON users(gender);
CREATE INDEX IF NOT EXISTS idx_users_seeking ON users(seeking);
CREATE INDEX IF NOT EXISTS idx_users_age ON users(age);

-- ============================================================
-- ЛАЙКИ / ДИЗЛАЙКИ
-- ============================================================
CREATE TABLE IF NOT EXISTS likes (
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    is_like    INTEGER NOT NULL DEFAULT 1,  -- 1 = like, 0 = dislike
    message    TEXT,                        -- сообщение с лайком (icebreaker)
    created_at INTEGER NOT NULL,
    PRIMARY KEY (from_id, to_id)
);

CREATE INDEX IF NOT EXISTS idx_likes_to_id_is_like ON likes(to_id, is_like);
CREATE INDEX IF NOT EXISTS idx_likes_created_at ON likes(created_at DESC);

-- ============================================================
-- МЭТЧИ (взаимные лайки)
-- ============================================================
CREATE TABLE IF NOT EXISTS matches (
    a_id       INTEGER NOT NULL,
    b_id       INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (a_id, b_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_a_id ON matches(a_id);
CREATE INDEX IF NOT EXISTS idx_matches_b_id ON matches(b_id);
CREATE INDEX IF NOT EXISTS idx_matches_created_at ON matches(created_at DESC);

-- ============================================================
-- ПОКАЗАННЫЕ АНКЕТЫ (для ленты — не показывать повторно)
-- ============================================================
CREATE TABLE IF NOT EXISTS shown_profiles (
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    shown_at   INTEGER NOT NULL,
    PRIMARY KEY (from_id, to_id)
);

CREATE INDEX IF NOT EXISTS idx_shown_profiles_from_id_shown_at ON shown_profiles(from_id, shown_at);
CREATE INDEX IF NOT EXISTS idx_shown_profiles_shown_at ON shown_profiles(shown_at);

-- ============================================================
-- ФОТОГАЛЕРЕЯ
-- ============================================================
CREATE TABLE IF NOT EXISTS photos (
    tg_id      INTEGER NOT NULL,
    photo_id   TEXT    NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0,  -- 0 = главное фото
    PRIMARY KEY (tg_id, position)
);

CREATE INDEX IF NOT EXISTS idx_photos_tg_id ON photos(tg_id);

-- ============================================================
-- АНОНИМНЫЙ ЧАТ — ОЧЕРЕДЬ
-- ============================================================
CREATE TABLE IF NOT EXISTS anon_queue (
    tg_id      INTEGER PRIMARY KEY,
    queued_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anon_queue_queued_at ON anon_queue(queued_at);

-- ============================================================
-- АНОНИМНЫЙ ЧАТ — СЕССИИ
-- ============================================================
CREATE TABLE IF NOT EXISTS anon_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    a_id       INTEGER NOT NULL,
    b_id       INTEGER NOT NULL,
    a_reveal   INTEGER DEFAULT 0,
    b_reveal   INTEGER DEFAULT 0,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_anon_sessions_active ON anon_sessions(a_id, b_id, ended_at) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_anon_sessions_a_id ON anon_sessions(a_id);
CREATE INDEX IF NOT EXISTS idx_anon_sessions_b_id ON anon_sessions(b_id);

-- ============================================================
-- ЖАЛОБЫ
-- ============================================================
CREATE TABLE IF NOT EXISTS reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_to_id ON reports(to_id);
CREATE INDEX IF NOT EXISTS idx_reports_from_id ON reports(from_id);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at DESC);

-- ============================================================
-- ТИКЕТЫ ПОДДЕРЖКИ
-- ============================================================
CREATE TABLE IF NOT EXISTS tickets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id      INTEGER NOT NULL,
    category   TEXT    NOT NULL,
    text       TEXT    NOT NULL,
    photo_id   TEXT,
    reply      TEXT,
    status     TEXT    DEFAULT 'open',
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_tg_id_status ON tickets(tg_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

-- ============================================================
-- ЗНАЧКИ (АРТЕФАКТЫ)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_badges (
    tg_id       INTEGER NOT NULL,
    badge_id    TEXT    NOT NULL,
    awarded_at  INTEGER NOT NULL,
    PRIMARY KEY (tg_id, badge_id)
);

CREATE INDEX IF NOT EXISTS idx_user_badges_badge_id ON user_badges(badge_id);

-- ============================================================
-- УРОВНИ ОТНОШЕНИЙ
-- ============================================================
CREATE TABLE IF NOT EXISTS relationships (
    user1_id   INTEGER NOT NULL,
    user2_id   INTEGER NOT NULL,
    points     INTEGER DEFAULT 0,
    level      INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user1_id, user2_id)
);

CREATE INDEX IF NOT EXISTS idx_relationships_points ON relationships(points DESC);
