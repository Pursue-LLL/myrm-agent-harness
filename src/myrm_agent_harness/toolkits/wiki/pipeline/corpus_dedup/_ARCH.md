# corpus_dedup/

Raw corpus deduplication governance: fingerprint scan, SQLite persistence, user disposition, and compile eligibility filtering.

## Overview

Three-tier duplicate detection (exact SHA256, normalized hash, simhash near-match) with four dispositions (trash, exclude, dismiss, defer). Trashed files move to `{vault_base}/.corpus_trash/`. Excluded/trashed paths are filtered from compile queue, compiler input, and stale detection. Exact/normalized open groups soft-block compile via server REST. Restore re-enqueues raw files for compile; body snippets support side-by-side review in Settings.

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Package | Public exports for scanner, governor, eligibility, store, types, snippets | ✅ |
| `path_utils.py` | SSOT | `normalize_raw_relative_path` — raw-dir-relative path keys | ✅ |
| `types.py` | Types | DedupTier, DispositionAction, DuplicateGroup, DuplicateMemberSnippet, ScanResult, DedupStats, VaultHygieneSnapshot | ✅ |
| `fingerprint.py` | Core | Exact/normalized/simhash fingerprint builders | ✅ |
| `store.py` | Core | SQLite `.raw_dedup.db` — groups, excludes, trash, `file_fingerprints` cache, scan progress, deferred member sets, hygiene listings | ✅ |
| `scanner.py` | Core | `CorpusDedupScanner` — incremental scan via fingerprint cache; deferred cluster matching on regroup | ✅ |
| `governor.py` | Core | `CorpusDedupGovernor` — trash/exclude/dismiss/defer · restore with compile enqueue · undo excluded raw | ✅ |
| `eligibility.py` | Core | `CorpusEligibilityFilter` — blocked-path filter for compile/queue/stale | ✅ |
| `snippets.py` | Core | `build_group_body_snippets` — capped body previews for duplicate review | ✅ |

## Key Dependencies

- `core.structure` (vault paths, raw listing)
- `core.claims_contract` (content hashing)
- `pipeline.raw_gate.evidence_removal` (re-anchor after trash)
- `pipeline.cognitive_map` (restore audit log entries)
- `memory._internal.hash_utils` (normalized text hash)

## Server Integration

Product layer bridges via `app/services/wiki/dedup_runner.py` — REST `/wiki/dedup/*` (POST scan → 202 + background task, GET progress, GET group snippets), cron `__wiki_dedup__`, non-blocking post-import and post-source-sync scan hooks.
