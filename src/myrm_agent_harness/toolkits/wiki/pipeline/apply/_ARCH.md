# pipeline/apply/

## Overview

Narrow-write wiki mutations for agents, chat capture, and Settings editors.
Operations transform content section-aware, then route through the deterministic
publication gate (`publication/gate.py`): human-originated settings writes publish
directly (WPG); agent and chat writes are staged as HITL pending drafts and publish
only after human approval (fail-closed).

## Files

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package marker for the apply module. | ✅ |
| `types.py` | Types | `WikiApplyOp`, `WikiApplyRequest`, `WikiApplyResult` (incl. `staged_for_review`, `pending_edit_id`) | ✅ |
| `errors.py` | Errors | `WikiApplyError` structured failures | ✅ |
| `handlers.py` | Core | Section/metadata transforms (no I/O) | ✅ |
| `service.py` | Core | Vault lock + deterministic publication routing (`caller=settings` → publish; `caller=agent|chat` → stage pending) | ✅ |

## Operations

| op | Scope |
|----|-------|
| `create_note` | New concept with FM skeleton + Compiled Truth/Timeline sections |
| `update_metadata` | Merge tags/aliases/sources/claims; optional clear_confidence |
| `patch_compiled_truth` | Replace `## Compiled Truth` + reconcile summary claim |
| `append_timeline` | Append-only Timeline with duplicate/length guards |
| `replace_full_document` | Settings-only full page replace |

Caller gates: `replace_full_document` is rejected unless `caller=settings`.
Chat wiki capture allows `update_metadata` only; create/patch/append must use the chat compound path.
All successful writes stamp `content_hash` (page lease) and enforce optional `if_match`.
`create_note` rejects canonical id / alias collisions via `toolkits/wiki/core/canonical_registry.py`.
Blocked publish outcomes (security scan) raise `WikiApplyError("publish_blocked")`.

## Dependencies

- `toolkits/wiki/core/section_contract.py` — managed block SSOT
- `toolkits/wiki/core/canonical_registry.py` — canonical id, alias index, page lease hash
- `toolkits/wiki/core/claims_contract.py` — claim merge + compile snapshots
- `pipeline/publication/gate.py` — deterministic publication routing (stage vs publish)
- `pipeline/pending.py` — HITL staging (via the gate's lazy import)
