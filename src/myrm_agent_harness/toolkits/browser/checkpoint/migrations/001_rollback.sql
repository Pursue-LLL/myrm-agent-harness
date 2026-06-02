-- Rollback Migration: Restore redundant fields to checkpoint_threads table
-- Date: 2026-03-23
-- Purpose: Rollback 001_remove_redundant_fields.sql if needed
--
-- WARNING: This rollback will restore the table structure but NOT the data
--          for checkpoint_count, recovery_count, last_url, session_domain.
--          These fields will be set to defaults (0 or NULL).

-- ============================================================================
-- SQLite Rollback
-- ============================================================================

-- Step 1: Create table with original schema
CREATE TABLE checkpoint_threads_rollback (
    thread_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    checkpoint_count INTEGER DEFAULT 0,
    recovery_count INTEGER DEFAULT 0,
    last_url TEXT,
    session_domain TEXT
);

-- Step 2: Copy data from current table
INSERT INTO checkpoint_threads_rollback (thread_id, status, created_at, last_active_at)
SELECT thread_id, status, created_at, last_active_at
FROM checkpoint_threads;

-- Step 3: Drop current table
DROP TABLE checkpoint_threads;

-- Step 4: Rename rollback table
ALTER TABLE checkpoint_threads_rollback RENAME TO checkpoint_threads;

-- Step 5: Recreate indexes
CREATE INDEX idx_threads_status ON checkpoint_threads(status);
CREATE INDEX idx_threads_last_active ON checkpoint_threads(last_active_at);

-- ============================================================================
-- PostgreSQL Rollback
-- ============================================================================

-- Step 1: Create table with original schema
CREATE TABLE checkpoint_threads_rollback (
    thread_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    last_active_at TIMESTAMPTZ NOT NULL,
    checkpoint_count INTEGER DEFAULT 0,
    recovery_count INTEGER DEFAULT 0,
    last_url TEXT,
    session_domain TEXT
);

-- Step 2: Copy data from current table
INSERT INTO checkpoint_threads_rollback (thread_id, status, created_at, last_active_at)
SELECT thread_id, status, created_at, last_active_at
FROM checkpoint_threads;

-- Step 3: Drop current table
DROP TABLE checkpoint_threads CASCADE;

-- Step 4: Rename rollback table
ALTER TABLE checkpoint_threads_rollback RENAME TO checkpoint_threads;

-- Step 5: Recreate indexes
CREATE INDEX idx_threads_status ON checkpoint_threads(status);
CREATE INDEX idx_threads_last_active ON checkpoint_threads(last_active_at);
