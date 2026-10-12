# lineage_defense/

## Overview

Lineage dedup and automation demotion suite for conversation recall. Harness framework layer package entry for Item 97. Strict typing applied: No `any` types allowed. Single file < 400 lines.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Lineage dedup and automation demotion suite for conversation recall — Harness framework layer package entry for Item 97. Strict typing applied: No `any` types allowed. Single file < 400 lines. | ✅ |
| demotion_engine.py | Core | Source-aware demotion engine for conversation recall — Harness framework layer engine for Item 97. Implements Hermes PR #19434 wisdom: demote, do not unconditionally drop cron sessions, ensuring interactive sessions surface first while cron remains reachable when only match. Strict typing applied: No `any` types allowed. Single file < 400 lines. | ✅ |
| lineage_dedup.py | Core | Lineage root generational deduplication engine for conversation recall — Harness framework layer engine for Item 97. Resolves multi-generation session pollution where 5 slices of the same long-running task compete for BM25 result slots, eliminating redundancy while preserving ancestry traceability. Strict typing applied: No `any` types allowed. Single file < 400 lines. | ✅ |
| models.py | Core | Data models and policies for conversation lineage dedup and automation demotion — Harness framework layer models for Item 97 (LineageDedupRecallBlindnessDefenseAndAutomationDemotionSuite). Strict typing applied: No `any` types allowed. Single file < 400 lines. | ✅ |
| window_hydrator.py | Core | Adaptive window hydration and token footprint economizer — Harness framework layer engine for Item 97. Dramatically reduces context token bloat (by ~70%+) and prevents LLM Lost-in-the-Middle attention drift by selectively hydrating deep context only for the highest-confidence primary hit. Strict typing applied: No `any` types allowed. Single file < 400 lines. | ✅ |
