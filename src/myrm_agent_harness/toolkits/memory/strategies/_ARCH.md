# strategies/

## Overview
Optional memory strategies: forgetting, extraction, deduplication, consolidation, preference stability, pattern discovery, staleness review.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Optional memory strategies: forgetting, extraction, deduplication, consolidation. | — |
| consolidation.py | Core | Cross-session memory consolidation strategy. Analyzes recent memories via LLM to detect contradictions, redundancies, and generate insights. | ✅ |
| consolidation_rollback.py | Core | Consolidation rollback. Reverses the most recent consolidation cycle using existing soft-deletion and metadata mechanisms. Zero extra storage. | ✅ |
| deduplicator.py | Core | Three-layer smart deduplication strategy. Layer 1: O(1) normalized hash with persistent cache | ✅ |
| extractor.py | Core | Automatic memory extractor. Regex pre-scan for tool edicts + LLM extraction of structured memories. Includes goal learnings extraction for post-goal actionable knowledge capture. | ✅ |
| forgetting.py | Core | Forgetting strategy. Calculates retention scores based on time decay, access frequency, | ✅ |
| llm_prompt.py | Core | LLM prompt for Layer 3 semantic deduplication judgment. | ✅ |
| pattern_discovery.py | Core | Cross-cycle pattern discovery. Analyzes accumulated memories and consolidation insights to surface behavioral patterns the user may not be aware of. Gated by memory count (≥50) and consolidation count (≥3). | ✅ |
| preference_stability.py | Core | Preference stability detection strategy. Manages user preference lifecycle through evidence accumulation, time decay, and category-aware half-lives. | ✅ |
| preference_stability_store.py | Core | Preference facet store — Protocol and SQLite implementation for persistent storage of preference metadata. | ✅ |
| recurrence.py | Core | Recurrence-triggered memory consolidation. Detects topics that appear repeatedly across sessions via embedding similarity, then triggers LLM refinement to produce high-quality long-term memories. Includes importance-preemption bypass for safety/health/identity signals. | ✅ |
| staleness_review.py | Core | LLM-driven staleness review. Identifies memories past their per-fact TTL (expected_valid_days) and submits for LLM semantic judgment (KEEP/EXTEND/REMOVE). Conservative: protects pinned, recently-accessed, and correction-chain memories. | ✅ |
| subsumption.py | Core | Cognitive consolidation engine. Identifies and safely soft-deletes old semantic memories | ✅ |

## Key Dependencies

- `infra`
