-- Migration: performance indexes (#7)
-- Date: 2026-07-10
-- Идемпотентно (CREATE INDEX IF NOT EXISTS). Кладётся в database/migrations/.
--
-- Узкое место — лента анкет (profile_repo.next_candidate*): для каждого
-- зрителя гоняется LEFT JOIN shown_profiles/likes + фильтры по users и
-- ORDER BY last_active. Ниже составные индексы под эти конкретные паттерны.

-- Лента: фильтр активных кандидатов с сортировкой по последней активности.
-- Частичный индекс — только по видимым анкетам, чтобы он был компактным.
CREATE INDEX IF NOT EXISTS idx_users_feed
    ON users (active, is_banned, last_active DESC);

-- Подбор по полу/возрасту в ленте.
CREATE INDEX IF NOT EXISTS idx_users_gender_age
    ON users (gender, age);

-- LEFT JOIN shown_profiles ON (from_id, to_id) — покрывающий индекс.
CREATE INDEX IF NOT EXISTS idx_shown_from_to
    ON shown_profiles (from_id, to_id);

-- Очистка старых показов по времени (cleanup_shown_profiles).
CREATE INDEX IF NOT EXISTS idx_shown_at
    ON shown_profiles (shown_at);

-- LEFT JOIN likes ON (from_id, to_id) в ленте + встречные лайки.
CREATE INDEX IF NOT EXISTS idx_likes_from_to
    ON likes (from_id, to_id);

-- incoming_likes: выборка входящих симпатий по получателю.
CREATE INDEX IF NOT EXISTS idx_likes_to_islike
    ON likes (to_id, is_like);

-- Активные анонимные сессии: WHERE ended_at IS NULL AND (a_id/b_id).
CREATE INDEX IF NOT EXISTS idx_anon_active_a
    ON anon_sessions (a_id, ended_at);
CREATE INDEX IF NOT EXISTS idx_anon_active_b
    ON anon_sessions (b_id, ended_at);

-- Очередь анонимного чата: подбор по времени ожидания.
CREATE INDEX IF NOT EXISTS idx_anon_queue_queued
    ON anon_queue (queued_at);

-- Значки пользователя (предзагрузка в next_candidate_full).
CREATE INDEX IF NOT EXISTS idx_user_badges_tg_id
    ON user_badges (tg_id);

ANALYZE;
