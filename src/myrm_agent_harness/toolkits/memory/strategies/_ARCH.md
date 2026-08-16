# strategies/

## Overview
Optional memory strategies: forgetting, extraction, deduplication, consolidation, preference stability, pattern discovery, staleness review.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Optional memory strategies: forgetting, extraction, deduplication, consolidation. | — |
| consolidation.py | Core | Cross-session memory consolidation strategy. Analyzes recent memories via LLM to detect contradictions, redundancies, and generate insights. | ✅ |
| consolidation_rollback.py | Core | Consolidation rollback. Reverses the most recent consolidation cycle using existing soft-deletion and metadata mechanisms. Zero extra storage. | ✅ |
| deduplicator.py | Core | Three-layer smart deduplication strategy. Layer 1: O(1) normalized hash with namespace-scoped persistent cache (`namespaces\|hash`); Layer 2: vector candidates filtered by memory's own `scope.namespaces`; Layer 3: LLM semantic judgment. `_apply_update` refuses cross-scope merge/replace (downgrades to NEW). | ✅ |
| extraction_domain.py | Core | Domain extraction presets — property hints injected into extraction LLM prompt for domain-specific recall precision. Presets: persona, work_assistant, research. Includes auto-detect from Agent system prompt. | ✅ |
| extractor.py | Core | Automatic memory extractor. Regex pre-scan for tool edicts + LLM extraction of structured memories. `ExtractionConfig.wiki_boundary_enabled` skips document-like facts when wiki is enabled. `domain_preset` injects domain-specific priority attributes. Uses `parse_llm_json_list` for robust extraction of the LLM output array (fences, prose, bare control chars, trailing commas, multiple arrays → last). | ✅ |
| forgetting.py | Core | Forgetting strategy. Calculates retention scores based on time decay, access frequency, | ✅ |
| llm_prompt.py | Core | LLM prompt for Layer 3 semantic deduplication judgment. | ✅ |
| pattern_discovery.py | Core | Cross-cycle pattern discovery. Analyzes accumulated memories and consolidation insights to surface behavioral patterns the user may not be aware of. Gated by memory count (≥50) and consolidation count (≥3). System prompt declares the exact output JSON field names (`title`/`description`/`evidence_summary`/`durability`/`confidence`/`actionable_suggestion`); `DiscoveredPattern` accepts LLM-natural aliases (`category`/`evidence`/`suggestion`) via `AliasChoices` so structured parsing never fails on field-name drift. | ✅ |
| preference_stability.py | Core | Preference stability detection strategy. Manages user preference lifecycle through evidence accumulation, time decay, and category-aware half-lives. | ✅ |
| preference_stability_store.py | Core | Preference facet store — Protocol and SQLite implementation for persistent storage of preference metadata. | ✅ |
| recurrence.py | Core | Recurrence-triggered memory consolidation. Detects topics that appear repeatedly across sessions via embedding similarity, then triggers LLM refinement to produce high-quality long-term memories. Includes importance-preemption bypass for safety/health/identity signals. | ✅ |
| implicit_feedback.py | Core | Session-level implicit feedback detection (regex + LLM) and memory correction planner. Produces structured CorrectionProposal (add/update/delete) for the Governance queue. Detection uses `parse_llm_json_object` (verdict object); planning uses `parse_llm_json_list` (action array) — robust against fences, prose, bare control chars, trailing commas. | ✅ |
| staleness_review.py | Core | LLM-driven staleness review. Identifies memories past their per-fact TTL (expected_valid_days) and submits for LLM semantic judgment (KEEP/EXTEND/REMOVE). Conservative: protects pinned, recently-accessed, and correction-chain memories. Parses the decision array via `parse_llm_json_list` (robust against fences, prose, trailing commas). | ✅ |
| subsumption.py | Core | Cognitive consolidation engine. Identifies and safely soft-deletes old semantic memories | ✅ |

## Key Dependencies

- `infra`
