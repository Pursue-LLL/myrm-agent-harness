# pipeline/apply/

## Overview

Narrow-write wiki mutations for agents, chat capture, and Settings editors.
All operations route through `publish_concept_article` (WPG) after section-aware transforms.

## Files

| File | Role |
|------|------|
| __init__.py | Package marker for the apply module. |
| types.py | `WikiApplyOp`, `WikiApplyRequest`, `WikiApplyResult` |
| errors.py | `WikiApplyError` structured failures |
| handlers.py | Section/metadata transforms (no I/O) |
| service.py | Vault lock + publish gate orchestration |

## Operations

| op | Scope |
|----|-------|
| `create_note` | New concept with FM skeleton + Compiled Truth/Timeline sections |
| `update_metadata` | Merge tags/aliases/sources/claims; optional clear_confidence |
| `patch_compiled_truth` | Replace `## Compiled Truth` + reconcile summary claim |
| `append_timeline` | Append-only Timeline with duplicate/length guards |
| `replace_full_document` | Settings-only full page replace |

Caller gates: `replace_full_document` is rejected unless `caller=settings`.
All successful writes stamp `content_hash` (page lease) and enforce optional `if_match`.
`create_note` rejects canonical id / alias collisions via `core/canonical_registry.py`.

## Dependencies

- `core/section_contract.py` — managed block SSOT
- `core/canonical_registry.py` — canonical id, alias index, page lease hash
- `core/claims_contract.py` — claim merge + compile snapshots
- `pipeline/publication/publish.py` — WPG publish gate
