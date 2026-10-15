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
| linter.py | Core | Health checker: …; `scan(mode)` read-only issue list; `lint_and_maintain(mode=STRUCTURAL|FULL)` — STRUCTURAL skips LLM drift/backlinks; post-maintain **vault git snapshot** when `enable_version_control`; inherits `_discover_connections` from `BacklinkDiscoveryMixin` | ✅ |
| backlink_discovery.py | Core | `BacklinkDiscoveryMixin._discover_connections`: asks the LLM which existing concepts an article should link to (the article body without its frontmatter; candidates are vault-relative page keys), parses the suggested wikilink array via `parse_llm_json_list` (robust against fences, prose, trailing commas), keeps the suggestions that resolve through `WikiLinkResolver` to a published local page that is not the article and not linked yet, and adds them to the article's Related Concepts section (`core/related_links`) through `publish_concept_article`. Scope: published local articles only (drafts, blocked pages, templates and mounted public wikis are neither rewritten nor offered as targets). Coverage: each run asks about the next 20 pages after the cursor stored in `.metadata.json` (`link_discovery_cursor`; wraps around; not advanced when the model answered for no page of the batch; a page that cannot take a link fails every run and does not hold it back), so call count per run stays 20 while every page gets its turn. The page is re-read after the model answers and merged without awaiting before the write, so an edit made during the call is kept; a hand-made page whose file name differs from the sanitized publish path (`Alpha Notes.md`) is linked to but never rewritten, since publishing would leave it untouched and write a sibling copy; the count is links actually added | ✅ |
| gap_issues.py | Core | `knowledge_gap_issues`: isolated/bridge insights → `knowledge_gap` lint issues, only for pages that exist in this vault (insights also cover read-only public mounts) | ✅ |
| issue_kind.py | Types | `action_kind_for_issue_type` + `count_open_actions` SSOT for health report UI lanes | ✅ |
| modes.py | Types | `MaintainMode` enum for cron vs manual maintain SSOT | ✅ |
| stale_summary.py | Core | Hash-based raw stale detection vs `last_compile_raw_hashes` snapshot; conservative all-raw-stale when compile time exists without hash snapshot; path set + concept stale-source matching + raw ingest tri-state resolver | ✅ |

## Key Dependencies

- `core` (config, structure, types)
- `retrieval` (indexer for FTS5/edge updates)
- `web_search` (optional, for deep research)
