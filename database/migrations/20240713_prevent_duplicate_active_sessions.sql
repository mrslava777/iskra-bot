-- Migration: prevent_duplicate_active_sessions
-- Applied: prevents a user from having multiple active anon_sessions simultaneously
-- This is the DB-level guarantee that works across multiple Railway containers.

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 1: Clean up existing duplicates
-- ═══════════════════════════════════════════════════════════════════════════════
-- For each user, keep only the newest active session (by started_at DESC, id DESC).
-- All older active sessions get ended_at = started_at (instant close).

WITH ranked AS (
    SELECT
        id,
        a_id,
        b_id,
        started_at,
        ROW_NUMBER() OVER (
            PARTITION BY a_id
            ORDER BY started_at DESC, id DESC
        ) AS rn_a,
        ROW_NUMBER() OVER (
            PARTITION BY b_id
            ORDER BY started_at DESC, id DESC
        ) AS rn_b
    FROM anon_sessions
    WHERE ended_at IS NULL
)
UPDATE anon_sessions
SET ended_at = started_at
WHERE id IN (
    SELECT id FROM ranked
    WHERE rn_a > 1 OR rn_b > 1
);

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 2: Create trigger function for session conflict check
-- ═══════════════════════════════════════════════════════════════════════════════
-- This trigger checks: neither a_id nor b_id may already be in an active session.
-- Works for both INSERT and UPDATE (in case someone tries to reactivate a session).

CREATE TRIGGER IF NOT EXISTS trg_anon_sessions_no_duplicate_active_insert
BEFORE INSERT ON anon_sessions
FOR EACH ROW
WHEN NEW.ended_at IS NULL
BEGIN
    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM anon_sessions
            WHERE ended_at IS NULL
              AND (
                  a_id = NEW.a_id
                  OR a_id = NEW.b_id
                  OR b_id = NEW.a_id
                  OR b_id = NEW.b_id
              )
        )
        THEN RAISE(ABORT, 'User already has an active anon_session')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_anon_sessions_no_duplicate_active_update
BEFORE UPDATE ON anon_sessions
FOR EACH ROW
WHEN NEW.ended_at IS NULL AND OLD.ended_at IS NOT NULL
BEGIN
    -- Only check when re-activating a previously ended session
    SELECT CASE
        WHEN EXISTS (
            SELECT 1 FROM anon_sessions
            WHERE ended_at IS NULL
              AND id != OLD.id
              AND (
                  a_id = NEW.a_id
                  OR a_id = NEW.b_id
                  OR b_id = NEW.a_id
                  OR b_id = NEW.b_id
              )
        )
        THEN RAISE(ABORT, 'User already has an active anon_session')
    END;
END;

-- ═══════════════════════════════════════════════════════════════════════════════
-- STEP 3: Partial unique indexes for extra safety (complementary to triggers)
-- ═══════════════════════════════════════════════════════════════════════════════
-- These catch edge cases the trigger might miss (e.g. concurrent transactions
-- in strict isolation levels). SQLite partial indexes are supported.

CREATE UNIQUE INDEX IF NOT EXISTS idx_anon_sessions_active_a
ON anon_sessions(a_id)
WHERE ended_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_anon_sessions_active_b
ON anon_sessions(b_id)
WHERE ended_at IS NULL;
