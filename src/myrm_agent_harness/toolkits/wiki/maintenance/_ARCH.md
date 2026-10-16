# maintenance/

## Overview
Wiki health checks and auto-maintenance. Broken link detection, completeness checks,
LLM-driven wikilink enrichment, and proactive knowledge-gap analysis
(isolated/bridge node detection via graph insights). Cross-concept contradiction
synthesis runs at compile time (`pipeline/contradiction_synthesis/`).

Deterministic broken markdown/wikilink links, frontmatter-type checks, and raw-backed provenance gaps live in `../diagnostics/structural_lint.py` (SSOT); `linter.py` delegates to that module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Wiki 维护模块入口包：聚合导出 WikiLinter 与 MaintainMode | ✅ |
| linter.py | Core | Health checker: …; `scan(mode)` read-only issue list; `lint_and_maintain(mode=STRUCTURAL|FULL)` — STRUCTURAL skips LLM drift/backlinks; post-maintain **vault git snapshot** when `enable_version_control`; inherits `_discover_connections` from `BacklinkDiscoveryMixin` and `_check_drift` from `DriftReviewMixin`; `lint_and_maintain(mode, on_progress=, stop=)` hands an optional observer to both LLM phases and one `AiCalls` per run; `LintResult.ai_unavailable` is set when the model was asked and answered nothing (structural repairs still ran), `LintResult.stopped` when the host set `stop` and the model phases ended early (everything written before stays; the run finishes through its normal path) | ✅ |
| backlink_discovery.py | Core | `BacklinkDiscoveryMixin._discover_connections`: asks the LLM which existing concepts an article should link to (the article body without its frontmatter; candidates are vault-relative page keys), parses the suggested wikilink array via `parse_llm_json_list` (robust against fences, prose, trailing commas), keeps the suggestions that resolve through `WikiLinkResolver` to a published local page that is not the article and not linked yet, and adds them to the article's Related Concepts section (`core/related_links`) through `publish_concept_article`. Scope: published local articles only (drafts, blocked pages, templates and mounted public wikis are neither rewritten nor offered as targets; a page that cannot be read or decoded is skipped). Coverage: each run asks about the next 20 pages after the cursor stored in `.metadata.json` (`link_discovery_cursor`; wraps around; not advanced when the model answered for no page of the batch; a page that cannot take a link fails every run and does not hold it back; a cursor that cannot be saved only repeats the batch; "answered for no page" is read off the run's `AiCalls`; a batch stopped by the host moves the cursor to the last page handled, so the next run continues there and pays for no page twice), so call count per run stays 20 while every page gets its turn. The page is re-read after the model answers and merged without awaiting before the write, so an edit made during the call is kept; a hand-made page whose file name differs from the sanitized publish path (`Alpha Notes.md`) is linked to but never rewritten, since publishing would leave it untouched and write a sibling copy; the count is links actually added | ✅ |
| drift_review.py | Core | `DriftReviewMixin._check_drift`: fact-checks up to 5 sampled articles against the raw sources their frontmatter cites (one LLM call per page, `NO_DRIFT` marker) and reports concrete discrepancies as `drift` issues; reports progress per sampled page | ✅ |
| ai_calls.py | Core | `AiCalls`: one run's model calls. Counts them (`ask` wraps `ainvoke`; a raised failure is counted and re-raised; `unavailable` = asked > 0 and every call raised) so a run with no working model (no provider, revoked key, provider down) is told apart from one with nothing to improve, and carries the host's optional `stop` event: once set, the call in flight is cancelled on the client (the maintain model is non-streaming, so the provider may still finish and bill that one completion; calls are serial, so a stop costs at most one extra call) and `ask` raises `MaintainStoppedError`, which the drift and discovery loops treat as the end of their phase (never as a failed page, never counted). Stopping ends a model call only, never a write; cancellation (`BaseException`) passes through uncounted. Link discovery reads the same counts to tell a batch the model answered for no page from a page that cannot take a link | ✅ |
| progress.py | Types | `MaintainPhase` (drift_review → link_discovery), `MaintainProgress(phase, done, total)`, `MaintainProgressCallback` and `report_progress`: a full run makes up to 25 sequential LLM calls (minutes), so the host can pass an observer that is told before each page and once at the end of a phase; the engine keeps no state and an observer that is missing or raises changes nothing | ✅ |
| gap_issues.py | Core | `knowledge_gap_issues`: isolated/bridge insights → `knowledge_gap` lint issues, only for pages that exist in this vault (insights also cover read-only public mounts) | ✅ |
| issue_kind.py | Types | `action_kind_for_issue_type` + `count_open_actions` SSOT for health report UI lanes | ✅ |
| modes.py | Types | `MaintainMode` enum for cron vs manual maintain SSOT | ✅ |
| stale_summary.py | Core | Hash-based raw stale detection vs `last_compile_raw_hashes` snapshot; conservative all-raw-stale when compile time exists without hash snapshot; path set + concept stale-source matching + raw ingest tri-state resolver | ✅ |

## Key Dependencies

- `core` (config, structure, types)
- `retrieval` (indexer for FTS5/edge updates)
- `web_search` (optional, for deep research)
