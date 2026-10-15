# core/

## Overview
Wiki core configuration, types, and file structure management. Includes purpose-driven
knowledge direction, compile/query configs, and recursive file system operations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Wiki 核心模块入口包：聚合导出配置、结构与核心数据模型 | ✅ |
| config.py | Config | WikiConfig, WikiQueryConfig (incl. index_first/sidecar/best-first/raw_claim knobs + `min_answer_confidence` refusal floor decoupled from `min_query_quality_score` archive gate), WikiCompileConfig | ✅ |
| parsers.py | Core | LLM response parsers — JSON (via `parse_llm_json_list`, robust against fences, prose, bare control chars, trailing commas) and bullet-point format to ConceptInfo list | ✅ |
| structure.py | Core | File system layout, OKF paths (`index.md`, `log.md`, `hot.md`, `SCHEMA.md`), frontmatter alias mtime-guarded process cache resolution (`resolve_alias_file_path`, `invalidate_alias_cache`), directory sidecar helpers, tree CRUD | ✅ |
| types.py | Types | Data models: ConceptInfo, WikiArticle, CompileResult (incl. publication counts), SourceSnippet (incl. claim citation + `claim_confidence` + `evidence_snapshot_status`), QueryResult (incl. `retrieval_trace`, derived `confidence_score`, `refused` fail-closed verdict), LintIssue, LintResult | ✅ |
| `frontmatter_contract.py` | Contract | WikiPageType (含 `metric`)+ WikiPublishStatus + WikiProvenance；validate/infer/repair `type` 与指标强类型前置校验；yaml-aware `load_frontmatter_metadata` / `serialize_frontmatter_block`；`resolve_publish_status` (a missing or unknown value reads as published; the one reader of a page's status, shared by the index publish gate and link discovery); `repair_publication_on_disk` grandfathers missing publish_status only (skips draft/blocked) | ✅ |
| claims_contract.py | Contract | OC-compatible structured `claims` parse/validate/merge; compile-time evidence `contentSha256` pin; read-time snapshot+excerpt with process LRU raw bytes cache (mtime invalidation); portable `last_compile_raw_hashes` + `raw_supersede`; `format_resource_uri` / `build_evidence_resource_uri` | ✅ |
| section_contract.py | Contract | Managed block SSOT: extract/replace/append + `parse_editor_sections` for GUI | ✅ |
| related_links.py | Contract | SSOT for a page's `## Related Concepts` section: `merge_related_links` appends the links the section lacks and edits nothing else (text already in the section and every other section stay as they are; a link counts as present when it names a page the section already links, however spelled, so spellings never duplicate; a page is never listed as related to itself; names that cannot be a one-line `[[...]]` target (line breaks, brackets) are dropped because they come from model output; a page that gains nothing is returned unchanged). The one writer for compile-time backlinks and maintenance link discovery | ✅ |
| link_extraction.py | Core | SSOT for link syntax: masks code (``` and ~~~ fences, backtick spans) before any link is read, parses `[[note#heading\|label]]`, drops URLs / anchors / `system:` pseudo targets, link parts are length-bounded so an unclosed `[[` cannot make a scan quadratic; shared by graph edges, structural lint, move/rename refactoring, backlink discovery and canvas import | ✅ |
| link_resolver.py | Core | SSOT for link resolution: per-page lookup keys (path, title, aliases, `canonical_id`, file name), `WikiLinkResolver` (lazy, incrementally maintained, ambiguity-safe; a bare file name resolves to the page in the linking page's folder, else to the only page of that name, the rule `refactor.py` applies on rename; shared by graph edges, structural lint and rename rewriting through `link_names_page` / `link_names_file`; a page that cannot be read or decoded is left out of the scan), `ambiguous_pages` (the pages an ambiguous target matches), `PageChange` (what a page that appeared, changed or disappeared means for stored edges, including the pages it collides with), and `concept_index_key` (the on-disk page key every index row is stored under) | ✅ |
| canonical_registry.py | Contract | `canonical_id` / alias index, page lease hash, write-time dedup helpers | ✅ |
| fact_trust_contract.py | Contract | FactStatus + FactTrustLevel + FactTrustPolicy; resolve_fact_status with frontmatter override and directory path inference | ✅ |
| refactor.py | Core | LinkRefactorEngine — RefactorReport, short-wikilink disambiguation, canonical_id pinning, supersedes/aliases injection, and markdown/wikilink updates across wiki move/rename events (links are read through `link_extraction`, so code is never rewritten; a wikilink is rewritten exactly when `link_resolver` points it at the moved page or, for a folder move, at a page under it: any spelling, folder prefix matched by path segments) | ✅ |
| `source_card_contract.py` | Contract | SourceCardContract, SourceProvenanceClass, SourceRiskLevel, validation, and frontmatter parser/serializer for Layer 2 (sources/) | ✅ |
| `negative_exclusion_policy.py` | Guard | Negative exclusion boundary policy enforcing deterministic filtering of 5 categories of ephemeral / single-session artifacts | ✅ |
| `radar_rationale_contract.py` | Contract | Three-way source radar ingestion contracts and formal ZeroYieldRationaleReport preventing low-grade batch pollution | ✅ |
