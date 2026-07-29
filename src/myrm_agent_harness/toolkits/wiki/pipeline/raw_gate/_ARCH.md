# raw_gate/

Raw publication gate — single SSOT for stable-path writes into vault `raw/`.

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `types.py` | Types | `RawConflictPolicy`, `RawPublishRequest`, `RawPublishResult` (+ security fields) | ✅ |
| `errors.py` | Types | `RawGateError` structured failures | ✅ |
| `security_hook.py` | Core | `apply_raw_security_scan`, `scan_publish_article_content` | ✅ |
| `forget.py` | Core | `forget_evidence`, `scan_existing_raw_vault` (blocked → unlink + optional FTS purge) | ✅ |
| `service.py` | Core | `publish_raw()` with per-vault asyncio lock + security pre-scan | ✅ |

Policies: `FAIL` (agent ingest), `SKIP` / `SUPERSEDE` (settings import), `PUT_IF_ABSENT` (query archive).

Supersede appends `RAW_SUPERSEDE` to `wiki/log.md` via cognitive map writer.

## Key Dependencies

- `core.structure` (raw path resolution)
- `core.canonical_registry` (content hash)
- `pipeline.cognitive_map.writer` (audit log append)
