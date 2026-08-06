# raw_gate/

Raw publication gate — single SSOT for stable-path writes into vault `raw/`.

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `types.py` | Types | `RawConflictPolicy`, `RawPublishRequest`, `RawPublishResult` (+ security fields) | ✅ |
| `errors.py` | Types | `RawGateError` structured failures | ✅ |
| `security_hook.py` | Core | `apply_raw_security_scan`, `scan_publish_article_content` | ✅ |
| `forget.py` | Core | `forget_evidence` permanent delete — delegates to `evidence_removal` | ✅ |
| `evidence_removal.py` | Core | `remove_raw_evidence` shared re-anchor SSOT (forget + dedup trash) | ✅ |
| `service.py` | Core | `publish_raw()` with per-vault asyncio lock + security pre-scan | ✅ |

Policies: `FAIL` (agent ingest), `SKIP` / `SUPERSEDE` (settings import), `PUT_IF_ABSENT` (query archive, turn digest, consolidation digest).

`RawGateCaller`: `agent` | `settings` | `chat` | `extension` (browser clip ingress).

Programmatic ingress (all via `publish_raw`): SessionNotes (`memory_to_wiki`), turn digest (`_skill_agent_review`), Deep Research (`stream_lane_factory`), consolidation digest (`consolidation_bridge`), agent `wiki_ingest`, Settings import, **browser extension clip** (`pipeline/ingress/publish_clip_ingress`).

Supersede appends `RAW_SUPERSEDE` to `wiki/log.md` via cognitive map writer and records `raw_supersede` lineage in wiki metadata (`claims_contract.record_raw_supersede_entry`).

## Key Dependencies

- `core.structure` (raw path resolution)
- `core.canonical_registry` (content hash)
- `pipeline.cognitive_map.writer` (audit log append)
