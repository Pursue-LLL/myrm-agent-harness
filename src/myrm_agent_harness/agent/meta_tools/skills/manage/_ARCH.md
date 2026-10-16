# manage/

## Overview
Skill management meta tool. Supports optional similarity checking to warn about semantically duplicate skills on save.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill management meta tool. | — |
| lock_manager.py | Core | Provides per-skill lock mechanism to prevent concurrent modifications. | ✅ |
| skill_manage_tool.py | Core | Skill management meta tool facade; LLM-facing TOOL_DESCRIPTION (EN/ZH) documents atomic batches, patch/save, lock/unlock and that a delete cannot be undone. | ✅ |
| batch_runner.py | Core | Atomic operations[] batch execution with snapshot rollback. Pre-batch snapshots are read through `SkillSnapshotReader` (the storage the write backend changes; defaults to the turn skill backend). A patch reads the SKILL.md it edits from that same storage first, so it can edit a skill saved in an earlier turn that is not mounted for this turn, and falls back to the turn skill backend for a skill the storage does not have (`SkillContentSource`). An undoable batch ends with the `myrm_skill_batch:` JSON footer for server Task Steps undo; a batch containing a delete is final: no commit hook, no batch id or footer, and the result says it cannot be undone. | ✅ |
| _manage_handlers.py | Core | Action execution handlers (save/patch/delete/write_file/remove_file/lock/unlock) and validators; `SkillContentSource` is the read side of a patch. | ✅ |

## Key Dependencies

- `backends`
- `utils`
