-- Migration 002: create migrations tracking table
CREATE TABLE IF NOT EXISTS _migrations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    filename   TEXT NOT NULL UNIQUE,
    applied_at INTEGER NOT NULL
);
