# summary/

## Overview
LLM-based structured summarization strategy with quality gate, circuit breaker, and message reconstruction.

## File Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Re-exports public summary APIs. |
| `summarizer.py` | Core | LLM-invoked structured summarization with streaming progress tracking, cache-safe invocation, aux-model context guard, and `_coerce_to_structured_summary` (converges `with_structured_output` dict / Pydantic model / `StructuredSummary` output before attribute access — JSON-mode providers return plain dict). |
| `summary_auditor.py` | Core | Quality gate that validates generated summaries for coverage and accuracy. |
| `summary_builder.py` | Core | Message history reconstruction after summarisation (protected head extraction, compacted messages assembly). |
| `summary_parser.py` | Core | Summary format parsing and message-to-text formatting with credential redaction. Uses `parse_llm_json_object` (robust against fences, prose, bare control chars, trailing commas) for LLM responses and `require_key="user_goal"` for summary-message scans. Embedded `<!-- SUMMARY_JSON` block parsing tolerates literal `-->` inside JSON values (loop-until-parse), skips unparseable summary blocks, and locates the **last** parseable summary block (reverse scan) — compaction rebuilds always place the newest summary block at the latest position, so the last block is the freshest incremental-merge base and stale multi-block residuals never cause information loss. `extract_messages_after_summary` anchors on the same last-parseable block so incremental inputs stay aligned with the extracted summary. `_build_summary_from_dict` is the single source of truth for dict→`StructuredSummary` mapping (all 14 fields incl. `blocked_items`/`next_steps`); `parse_structured_summary_json` exposes the strict-JSON variant (None on failure) for business-layer persistence boundaries (server `compacted_summary`) so incremental-merge bases never drop fields. |
| `summary_prompts.py` | Core | Prompt templates for structured JSON summary and merge operations. |
| `summarize_circuit_guard.py` | Core | Circuit breaker shared by turn pipeline and server compact paths. |
| `progress_timeout.py` | Core | Progress-aware timeout primitives for detecting stalled summarization (InactivityTimeoutError, TotalCeilingTimeoutError). |
| `dropped_manifest.py` | Core | Dropped-constraint manifest builder for the compaction pipeline. Records redacted+truncated constraint snippets evicted by compaction so the GUI can distinguish "compaction dropped my constraint" from "the model ignored it" (fault-side attribution). Zero prompt cost — attached to StructuredSummary as audit metadata, excluded from `to_json()` so prompt-cache payloads never inflate. Exports `build_dropped_manifest` (pure) + `contains_constraint_marker` (shared matcher). |

## Key Dependencies

- `...infra.schemas` (ContextConfig, StructuredSummary)
- `...tracking.artifact_tracker`
- `security.detection.leak_detector`
