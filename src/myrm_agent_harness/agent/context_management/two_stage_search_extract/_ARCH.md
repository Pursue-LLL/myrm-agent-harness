# two_stage_search_extract/

## Overview
Two-stage ranked snippet triage and selective deep web extraction subsystem (Item 327, P0). Replaces explosive full-page web dump (30K~50K tokens) with a lightweight Stage 1 snippet triage pipeline capped strictly at 500 tokens, combined with an agent-directed Stage 2 selective deep fetch engine equipped with HTML boilerplate noise removal, per-turn concurrency limits (max 2 URLs), session-level budget governance, interim synthesis gates, and session coalescing deduplication caching.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package facade exporting two-stage search extract models, triage engine, cleaner, cache, and facade suite. | — |
| search_extract_types.py | Types | Strongly typed data structures for ranked snippet items, triage results, deep extract results, budget status, and configuration. | ✅ |
| snippet_triage_engine.py | Core | Stage 1 lightweight snippet triage engine bounding token usage strictly within 500 tokens with meta-guidance. | ✅ |
| deep_extract_cleaner.py | Core | Stage 2 selective deep web content cleanser stripping navigation, scripts, ads, and normalizing dense markdown. | ✅ |
| session_coalescing_cache.py | Core | Session-level in-memory coalescing cache for search triage snippets and deep extracted documents with TTL. | ✅ |
| fetch_budget_governor.py | Core | Concurrency and depth governor preventing runaway crawling and enforcing interim synthesis gates. | ✅ |
| two_stage_search_suite.py | Facade | Unified facade suite orchestrating two-stage search triage, deep extraction, budget limits, and caching. | ✅ |

## Key Dependencies

- stdlib: `urllib.parse`, `dataclasses`, `datetime`, `re`, `typing`
- Internal: `myrm_agent_harness.agent.context_management`
