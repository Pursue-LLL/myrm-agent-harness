-- Migration: Remove redundant fields from checkpoint_threads table
-- Date: 2026-03-23
-- Purpose: Simplify ThreadStore schema by removing unused monitoring fields
--
-- Rationale:
--   - checkpoint_count, recovery_count, last_url, session_domain are not used in production
--   - Monitoring data is available in LangGraph checkpoint metadata
--   - Reduces schema complexity and maintenance overhead
--
-- Affected fields:
--   REMOVED: checkpoint_count, recovery_count, last_url, session_domain
--   RETAINED: thread_id, status, created_at, last_active_at
--
-- Backward compatibility: None (breaking schema change)
-- Rollback: Use 001_rollback.sql if needed

-- ============================================================================
-- SQLite Migration
-- ============================================================================

-- SQLite does not support DROP COLUMN, so we need to recreate the table

-- Step 1: Create new table with simplified schema
CREATE TABLE checkpoint_threads_new (
    thread_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);

-- Step 2: Copy data from old table (only essential fields)
INSERT INTO checkpoint_threads_new (thread_id, status, created_at, last_active_at)
SELECT thread_id, status, created_at, last_active_at
FROM checkpoint_threads;

-- Step 3: Drop old table
DROP TABLE checkpoint_threads;

-- Step 4: Rename new table
ALTER TABLE checkpoint_threads_new RENAME TO checkpoint_threads;

-- Step 5: Recreate indexes
CREATE INDEX idx_threads_status ON checkpoint_threads(status);
CREATE INDEX idx_threads_last_active ON checkpoint_threads(last_active_at);

-- ============================================================================
-- PostgreSQL Migration
-- ============================================================================

-- PostgreSQL supports DROP COLUMN, but for consistency use the same approach

-- Step 1: Create new table with simplified schema
CREATE TABLE checkpoint_threads_new (
    thread_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    last_active_at TIMESTAMPTZ NOT NULL
);

-- Step 2: Copy data from old table (only essential fields)
INSERT INTO checkpoint_threads_new (thread_id, status, created_at, last_active_at)
SELECT thread_id, status, created_at, last_active_at
FROM checkpoint_threads;

-- Step 3: Drop old table (cascade to drop dependent objects)
DROP TABLE checkpoint_threads CASCADE;

-- Step 4: Rename new table
ALTER TABLE checkpoint_threads_new RENAME TO checkpoint_threads;

-- Step 5: Recreate indexes
CREATE INDEX idx_threads_status ON checkpoint_threads(status);
CREATE INDEX idx_threads_last_active ON checkpoint_threads(last_active_at);

-- ============================================================================
-- Verification Queries
-- ============================================================================

-- Check table schema (SQLite)
-- PRAGMA table_info(checkpoint_threads);

-- Check table schema (PostgreSQL)
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'checkpoint_threads'
-- ORDER BY ordinal_position;

-- Check record count before/after
-- SELECT COUNT(*) FROM checkpoint_threads;
