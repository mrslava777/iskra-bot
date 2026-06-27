"""Database schema documentation.

Таблицы:
- users: tg_id, username, name, age, gender, seeking, city, bio, interests, photo_id, active, verified, is_banned, created_at, last_active, streak, rating, daily_q, daily_a, anon_messages_count
- photos: id, tg_id, photo_id, position
- likes: id, from_id, to_id, is_like, message, created_at
- matches: id, a_id, b_id, created_at
- shown_profiles: from_id, to_id, shown_at
- reports: id, from_id, to_id, created_at
- anon_queue: tg_id, queued_at
- anon_sessions: id, a_id, b_id, a_reveal, b_reveal, started_at, ended_at
- relationships: id, user1_id, user2_id, points, level, created_at
- tickets: id, tg_id, category, text, photo_id, reply, status, created_at
- user_badges: tg_id, badge_id, awarded_at
"""
