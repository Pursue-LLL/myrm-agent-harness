"""Atomic batch execution for skill_manage_tool operations.

[INPUT]
- _manage_handlers action handlers
- backends.skills.protocols::SkillBackend (the turn's skills: snapshot reads when the host gives no dedicated reader,
  and where a patch looks for a skill the writer's storage lacks)

[OUTPUT]
- run_skill_manage_batch: execute operations with snapshot/rollback
- SkillSnapshotReader: where a host points the pre-batch snapshot reads

[POS]
Framework batch runner. Snapshots touched skills before applying ops; rolls back on failure.
A batch that deletes a skill is final: a deleted package cannot be rebuilt from a SKILL.md snapshot, so it gets
no undo record (no hook call, no batch id or undo hint in the output).
lock/unlock change the evolution store, which a snapshot cannot capture: they run after every file change has
succeeded, a failed batch puts each lock it changed back to its previous state, a batch that only locks changed no
file and so gets no undo record either, and the undo of a mixed batch leaves its locks as they are (the hint says so).
A patch edits the SKILL.md in the storage the writer overwrites when that storage has the skill, and only otherwise
the turn's skill backend: the backend lists the skills mounted for the turn, so it cannot see one the agent saved
earlier, and a stale view of a skill would be patched and then written over the newer file.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from myrm_agent_harness.agent.meta_tools.skills.manage._manage_handlers import (
    SkillContentSource,
    _evolution_lock_state,
    _handle_delete,
    _handle_evolution_lock,
    _handle_patch,
    _handle_remove_file,
    _handle_save,
    _handle_write_file,
    _validate_name,
)

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.protocols import SkillBackend
    from myrm_agent_harness.backends.skills.scanning import ScanningSkillWriteBackend
    from myrm_agent_harness.backends.skills.similarity import SkillSimilarityChecker

logger = logging.getLogger(__name__)

BATCH_MAX_OPS = 25

# Machine-readable batch id footer (parsed server-side for Task Steps undo).
SKILL_BATCH_JSON_PREFIX = "myrm_skill_batch:"

# lock/unlock change the evolution store, never a skill's files, so a snapshot can neither capture nor restore them.
_LOCK_ACTIONS = ("lock", "unlock")
_ACTIONS = ("save", "patch", "delete", "write_file", "remove_file", *_LOCK_ACTIONS)


@dataclass
class SkillBatchSnapshot:
    """Pre-mutation disk state for one skill (used for rollback and server persistence)."""

    skill_name: str
    skill_md: str | None
    resources: dict[str, str | None] = field(default_factory=dict)
    existed_before_batch: bool = True


class SkillManageBatchCommittedHook(Protocol):
    """Optional server hook to persist batch snapshots after successful commit."""

    async def on_batch_committed(
        self,
        batch_id: str,
        snapshots: dict[str, SkillBatchSnapshot],
    ) -> None: ...


class SkillSnapshotReader(Protocol):
    """Reads a skill's files from the storage the write backend changes, i.e. the state a rollback must restore.

    A turn's skill backend lists only the skills mounted for that turn: it cannot see a skill the agent created
    earlier in the turn or one outside its allowlist, and a snapshot taken through it would call such a skill
    "new", so undoing the batch would delete it. ``SkillBackend`` satisfies this protocol; a host whose writer
    stores skills elsewhere passes a reader over that storage.
    """

    async def get_skill_content(self, skill_name: str) -> str: ...

    async def get_skill_resources(self, skill_name: str, path: str) -> bytes: ...


async def _read_skill_md(reader: SkillSnapshotReader | None, name: str) -> str | None:
    if reader is None:
        return None
    try:
        content = await reader.get_skill_content(name)
        return content if content.strip() else None
    except Exception:
        return None


async def _read_resource(reader: SkillSnapshotReader | None, name: str, path: str) -> str | None:
    if reader is None or not path:
        return None
    try:
        raw = await reader.get_skill_resources(name, path)
        return raw.decode("utf-8")
    except Exception:
        return None


async def _capture_snapshots(
    reader: SkillSnapshotReader | None,
    skill_names: set[str],
    resource_paths_by_skill: dict[str, set[str]],
) -> dict[str, SkillBatchSnapshot]:
    snapshots: dict[str, SkillBatchSnapshot] = {}
    for name in sorted(skill_names):
        md = await _read_skill_md(reader, name)
        existed = md is not None
        resources: dict[str, str | None] = {}
        for path in sorted(resource_paths_by_skill.get(name, set())):
            resources[path] = await _read_resource(reader, name, path)
        snapshots[name] = SkillBatchSnapshot(
            skill_name=name,
            skill_md=md,
            resources=resources,
            existed_before_batch=existed,
        )
    return snapshots


class _FirstSourceWithSkill:
    """A skill's SKILL.md from the first source that has it, in the order given."""

    def __init__(self, sources: list[SkillContentSource]) -> None:
        self._sources = sources

    async def get_skill_content(self, skill_name: str) -> str:
        for source in self._sources:
            try:
                return await source.get_skill_content(skill_name)
            except FileNotFoundError:
                continue
        raise FileNotFoundError(skill_name)


def _patch_source(
    snapshot_reader: SkillSnapshotReader | None, skill_backend: SkillBackend | None
) -> SkillContentSource | None:
    sources: list[SkillContentSource] = [source for source in (snapshot_reader, skill_backend) if source is not None]
    return _FirstSourceWithSkill(sources) if sources else None


async def _restore_snapshot(
    write_backend: ScanningSkillWriteBackend,
    snapshot: SkillBatchSnapshot,
) -> None:
    name = snapshot.skill_name
    if not snapshot.existed_before_batch and snapshot.skill_md is None:
        await _handle_delete(write_backend, name)
        return

    if snapshot.skill_md is not None:
        await write_backend.save_skill(name=name, content=snapshot.skill_md, description="")

    for path, content in snapshot.resources.items():
        if content is None:
            await write_backend.delete_resource(name, path)
        else:
            await write_backend.write_resource(name, path, content)


def _normalize_op(raw: dict[str, object], index: int) -> tuple[str | None, dict[str, object]]:
    action = raw.get("action")
    if action not in _ACTIONS:
        return f"operations[{index}]: invalid or missing 'action'.", raw
    name = raw.get("name") or ""
    name_error = _validate_name(str(name))
    if name_error:
        return f"operations[{index}]: {name_error}", raw
    return None, raw


def _collect_touch_sets(
    operations: list[dict[str, object]],
) -> tuple[set[str], dict[str, set[str]]]:
    skill_names: set[str] = set()
    resources: dict[str, set[str]] = {}
    for op in operations:
        action = op.get("action")
        if action in _LOCK_ACTIONS:
            continue
        name = str(op.get("name", ""))
        skill_names.add(name)
        if action in ("write_file", "remove_file"):
            path = str(op.get("file_path") or op.get("resource_path") or "")
            if path:
                resources.setdefault(name, set()).add(path)
    return skill_names, resources


async def _run_single_op(
    write_backend: ScanningSkillWriteBackend,
    patch_source: SkillContentSource | None,
    similarity_checker: SkillSimilarityChecker | None,
    op: dict[str, object],
    index: int,
) -> str:
    action = op["action"]
    name = str(op["name"])
    if action == "save":
        return await _handle_save(
            write_backend,
            name,
            str(op.get("content") or ""),
            str(op.get("description") or ""),
            similarity_checker,
        )
    if action == "patch":
        return await _handle_patch(
            write_backend,
            patch_source,
            name,
            str(op.get("old_content") or ""),
            str(op.get("new_content") or ""),
        )
    if action == "delete":
        return await _handle_delete(write_backend, name)
    if action == "write_file":
        return await _handle_write_file(
            write_backend,
            name,
            str(op.get("file_path") or ""),
            str(op.get("content") or ""),
        )
    if action == "remove_file":
        return await _handle_remove_file(
            write_backend,
            name,
            str(op.get("file_path") or ""),
        )
    if action in _LOCK_ACTIONS:
        return await _handle_evolution_lock(name, locked=(action == "lock"))
    return f"Error: operations[{index}] unsupported action '{action}'."


def _execution_order(operations: list[dict[str, object]]) -> list[tuple[int, dict[str, object]]]:
    """The operations with their listed index, file changes first and lock/unlock after them, each group as listed.

    A lock lives outside the snapshots, so it only changes once every file change has succeeded: a batch that fails
    on a file change never reaches a lock listed before it.
    """
    return sorted(enumerate(operations), key=lambda indexed: indexed[1]["action"] in _LOCK_ACTIONS)


@dataclass(frozen=True)
class _ChangedLock:
    """A lock the batch changed, with the state it was in before."""

    skill_name: str
    was_locked: bool


async def _roll_back_batch(
    write_backend: ScanningSkillWriteBackend,
    snapshots: dict[str, SkillBatchSnapshot],
    changed_locks: list[_ChangedLock],
    batch_id: str,
) -> None:
    """Undo a batch that did not commit: every skill back to its snapshot, every changed lock back to its old state."""
    for name in sorted(snapshots, reverse=True):
        try:
            await _restore_snapshot(write_backend, snapshots[name])
        except Exception as restore_exc:
            logger.error("Rollback failed for skill %s in batch %s: %s", name, batch_id, restore_exc)
    for changed in reversed(changed_locks):
        outcome = await _handle_evolution_lock(changed.skill_name, locked=changed.was_locked)
        if _is_error_result(outcome):
            logger.error("Lock rollback failed for skill %s in batch %s: %s", changed.skill_name, batch_id, outcome)


def _is_error_result(message: str) -> bool:
    lower = message.lower()
    return lower.startswith("error") or lower.startswith("error:")


def _batch_id_footer(batch_id: str) -> str:
    payload = json.dumps({"batch_id": batch_id}, separators=(",", ":"))
    return f"\n{SKILL_BATCH_JSON_PREFIX}{payload}"


def _batch_undo_hint(locale: str | None, *, includes_locks: bool) -> str:
    from myrm_agent_harness.utils.locale import is_chinese

    if is_chinese(locale):
        hint = "\n\n在 Web 对话的「任务步骤」中可使用「撤销技能修改」，恢复本批次修改前的技能内容。"
        return hint + ("lock/unlock 的变更不在撤销范围内。" if includes_locks else "")
    hint = '\n\nIn chat Task Steps, use "Undo skill changes" to restore skill content from before this batch.'
    return hint + (" Lock and unlock changes are not part of the undo." if includes_locks else "")


def _final_batch_note(locale: str | None) -> str:
    from myrm_agent_harness.utils.locale import is_chinese

    if is_chinese(locale):
        return "\n\n已删除的技能无法撤销。"
    return "\n\nA deleted skill cannot be restored; there is no undo for it."


async def run_skill_manage_batch(
    *,
    write_backend: ScanningSkillWriteBackend,
    skill_backend: SkillBackend | None,
    similarity_checker: SkillSimilarityChecker | None,
    operations: list[dict[str, object]],
    batch_committed_hook: SkillManageBatchCommittedHook | None = None,
    snapshot_reader: SkillSnapshotReader | None = None,
    locale: str | None = None,
) -> str:
    """Apply skill_manage operations atomically; rollback snapshots on any failure.

    Snapshots are read through ``snapshot_reader`` when the host gives one, otherwise through ``skill_backend``. A
    patch edits the content ``snapshot_reader`` has for the skill and falls back to ``skill_backend`` for a skill the
    reader lacks.
    """
    if not operations:
        return "Error: 'operations' must be a non-empty array."
    if len(operations) > BATCH_MAX_OPS:
        return f"Error: at most {BATCH_MAX_OPS} operations per call."

    normalized: list[dict[str, object]] = []
    for i, raw in enumerate(operations):
        if not isinstance(raw, dict):
            return f"Error: operations[{i}] must be an object."
        err, op = _normalize_op(raw, i)
        if err:
            return f"Error: {err}"
        normalized.append(op)

    if any(op.get("action") == "delete" for op in normalized) and len(normalized) != 1:
        return "Error: 'delete' must be the only operation in the batch."

    skill_names, resource_paths = _collect_touch_sets(normalized)
    snapshots = await _capture_snapshots(
        snapshot_reader if snapshot_reader is not None else skill_backend, skill_names, resource_paths
    )
    batch_id = str(uuid.uuid4())
    patch_source = _patch_source(snapshot_reader, skill_backend)
    results: dict[int, str] = {}
    changed_locks: list[_ChangedLock] = []

    try:
        for i, op in _execution_order(normalized):
            name = str(op["name"])
            was_locked = _evolution_lock_state(name) if op["action"] in _LOCK_ACTIONS else None
            msg = await _run_single_op(write_backend, patch_source, similarity_checker, op, i)
            if _is_error_result(msg):
                raise RuntimeError(f"operations[{i}] ({op['action']} on '{name}'): {msg}")
            if was_locked is not None:
                changed_locks.append(_ChangedLock(skill_name=name, was_locked=was_locked))
            results[i] = msg
    except Exception as exc:
        logger.warning("skill_manage batch %s failed, rolling back: %s", batch_id, exc)
        await _roll_back_batch(write_backend, snapshots, changed_locks, batch_id)
        return f"Error: batch aborted (batch_id={batch_id}). No partial changes were kept.\nCause: {exc}"

    report = "\n---\n".join(results[i] for i in sorted(results))
    # A deleted package cannot be rebuilt from its SKILL.md snapshot, so a delete is final and leaves no undo record.
    if any(op["action"] == "delete" for op in normalized):
        return report + _final_batch_note(locale)
    # A batch that only locks or unlocks changed no file: nothing to restore, so no undo record either.
    if not snapshots:
        return report

    if batch_committed_hook is not None:
        try:
            await batch_committed_hook.on_batch_committed(batch_id, snapshots)
        except Exception as hook_exc:
            logger.error("batch_committed_hook failed for %s: %s", batch_id, hook_exc)
            await _roll_back_batch(write_backend, snapshots, changed_locks, batch_id)
            return (
                f"Error: batch aborted after persistence hook failure (batch_id={batch_id}). "
                f"Changes were rolled back. Cause: {hook_exc}"
            )

    includes_locks = any(op["action"] in _LOCK_ACTIONS for op in normalized)
    return (
        f"Batch applied successfully (batch_id={batch_id}, operations={len(results)}).\n\n"
        + report
        + _batch_id_footer(batch_id)
        + _batch_undo_hint(locale, includes_locks=includes_locks)
    )
