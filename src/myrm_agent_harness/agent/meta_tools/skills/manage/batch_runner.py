"""Atomic batch execution for skill_manage_tool operations.

[INPUT]
- _manage_handlers action handlers
- backends.skills.protocols::SkillBackend (optional snapshot reads)

[OUTPUT]
- run_skill_manage_batch: execute operations with snapshot/rollback

[POS]
Framework batch runner. Snapshots touched skills before applying ops; rolls back on failure.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from myrm_agent_harness.agent.meta_tools.skills.manage._manage_handlers import (
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

BatchAction = Literal["save", "patch", "delete", "write_file", "remove_file", "lock", "unlock"]


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
    ) -> None:
        ...


async def _read_skill_md(skill_backend: SkillBackend | None, name: str) -> str | None:
    if skill_backend is None:
        return None
    try:
        content = await skill_backend.get_skill_content(name)
        return content if content.strip() else None
    except Exception:
        return None


async def _read_resource(skill_backend: SkillBackend | None, name: str, path: str) -> str | None:
    if skill_backend is None or not path:
        return None
    try:
        raw = await skill_backend.get_skill_resources(name, path)
        return raw.decode("utf-8")
    except Exception:
        return None


async def _capture_snapshots(
    skill_backend: SkillBackend | None,
    skill_names: set[str],
    resource_paths_by_skill: dict[str, set[str]],
) -> dict[str, SkillBatchSnapshot]:
    snapshots: dict[str, SkillBatchSnapshot] = {}
    for name in sorted(skill_names):
        md = await _read_skill_md(skill_backend, name)
        existed = md is not None
        resources: dict[str, str | None] = {}
        for path in sorted(resource_paths_by_skill.get(name, set())):
            resources[path] = await _read_resource(skill_backend, name, path)
        snapshots[name] = SkillBatchSnapshot(
            skill_name=name,
            skill_md=md,
            resources=resources,
            existed_before_batch=existed,
        )
    return snapshots


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


def _normalize_op(raw: dict[str, Any], index: int) -> tuple[str | None, dict[str, Any]]:
    action = raw.get("action")
    if action not in (
        "save",
        "patch",
        "delete",
        "write_file",
        "remove_file",
        "lock",
        "unlock",
    ):
        return f"operations[{index}]: invalid or missing 'action'.", raw
    name = raw.get("name") or ""
    name_error = _validate_name(str(name))
    if name_error:
        return f"operations[{index}]: {name_error}", raw
    return None, raw


def _collect_touch_sets(
    operations: list[dict[str, Any]],
) -> tuple[set[str], dict[str, set[str]]]:
    skill_names: set[str] = set()
    resources: dict[str, set[str]] = {}
    for op in operations:
        name = str(op.get("name", ""))
        skill_names.add(name)
        action = op.get("action")
        if action in ("write_file", "remove_file"):
            path = str(op.get("file_path") or op.get("resource_path") or "")
            if path:
                resources.setdefault(name, set()).add(path)
    return skill_names, resources


async def _run_single_op(
    write_backend: ScanningSkillWriteBackend,
    skill_backend: SkillBackend | None,
    similarity_checker: SkillSimilarityChecker | None,
    op: dict[str, Any],
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
            skill_backend,
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
    if action in ("lock", "unlock"):
        return await _handle_evolution_lock(name, locked=(action == "lock"))
    return f"Error: operations[{index}] unsupported action '{action}'."


def _is_error_result(message: str) -> bool:
    lower = message.lower()
    return lower.startswith("error") or lower.startswith("error:")


def _batch_id_footer(batch_id: str) -> str:
    payload = json.dumps({"batch_id": batch_id}, separators=(",", ":"))
    return f"\n{SKILL_BATCH_JSON_PREFIX}{payload}"


def _batch_undo_hint(locale: str | None) -> str:
    from myrm_agent_harness.utils.locale import is_chinese

    if is_chinese(locale):
        return (
            "\n\n在 Web 对话的「任务步骤」中可使用「撤销技能修改」，"
            "恢复本批次修改前的技能内容。"
        )
    return (
        '\n\nIn chat Task Steps, use "Undo skill changes" to restore '
        "skill content from before this batch."
    )


async def run_skill_manage_batch(
    *,
    write_backend: ScanningSkillWriteBackend,
    skill_backend: SkillBackend | None,
    similarity_checker: SkillSimilarityChecker | None,
    operations: list[dict[str, Any]],
    batch_committed_hook: SkillManageBatchCommittedHook | None = None,
    locale: str | None = None,
) -> str:
    """Apply skill_manage operations atomically; rollback snapshots on any failure."""
    if not operations:
        return "Error: 'operations' must be a non-empty array."
    if len(operations) > BATCH_MAX_OPS:
        return f"Error: at most {BATCH_MAX_OPS} operations per call."

    normalized: list[dict[str, Any]] = []
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
    snapshots = await _capture_snapshots(skill_backend, skill_names, resource_paths)
    batch_id = str(uuid.uuid4())
    results: list[str] = []

    try:
        for i, op in enumerate(normalized):
            msg = await _run_single_op(
                write_backend,
                skill_backend,
                similarity_checker,
                op,
                i,
            )
            if _is_error_result(msg):
                raise RuntimeError(f"operations[{i}] ({op['action']} on '{op['name']}'): {msg}")
            results.append(msg)
    except Exception as exc:
        logger.warning("skill_manage batch %s failed, rolling back: %s", batch_id, exc)
        for name in sorted(snapshots.keys(), reverse=True):
            try:
                await _restore_snapshot(write_backend, snapshots[name])
            except Exception as restore_exc:
                logger.error("Rollback failed for skill %s in batch %s: %s", name, batch_id, restore_exc)
        return (
            f"Error: batch aborted (batch_id={batch_id}). No partial changes were kept.\n"
            f"Cause: {exc}"
        )

    if batch_committed_hook is not None:
        try:
            await batch_committed_hook.on_batch_committed(batch_id, snapshots)
        except Exception as hook_exc:
            logger.error("batch_committed_hook failed for %s: %s", batch_id, hook_exc)
            for name in sorted(snapshots.keys(), reverse=True):
                try:
                    await _restore_snapshot(write_backend, snapshots[name])
                except Exception as restore_exc:
                    logger.error("Post-hook rollback failed for %s: %s", name, restore_exc)
            return (
                f"Error: batch aborted after persistence hook failure (batch_id={batch_id}). "
                f"Changes were rolled back. Cause: {hook_exc}"
            )

    summary = (
        f"Batch applied successfully (batch_id={batch_id}, operations={len(results)}).\n\n"
        + "\n---\n".join(results)
        + _batch_id_footer(batch_id)
        + _batch_undo_hint(locale)
    )
    return summary
