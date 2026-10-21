"""Compact oversized parallel task results before swarm fission resume."""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.executor import _auto_vault_or_truncate
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

_DEFAULT_VAULT_THRESHOLD = 8000


def _compact_result_text(
    raw_result: str,
    *,
    workspace_path: str | None,
    task_index: int,
    agent_type: str,
    vault_threshold: int,
) -> str:
    config = SubagentConfig(
        system_prompt="",
        auto_vault_threshold=vault_threshold,
    )
    return _auto_vault_or_truncate(
        raw_result,
        config,
        {"workspace_path": workspace_path} if workspace_path else {},
        f"fission-{task_index}",
        agent_type,
    )


def compact_batch_results_for_resume(
    batch_dict: dict[str, object],
    *,
    workspace_path: str | None,
    vault_threshold: int = _DEFAULT_VAULT_THRESHOLD,
) -> dict[str, object]:
    """Vault or truncate large per-task result strings in a batch resume payload."""
    raw_results = batch_dict.get("results")
    if not isinstance(raw_results, list):
        return batch_dict

    compacted: list[dict[str, object]] = []
    changed = False
    for index, entry in enumerate(raw_results):
        if not isinstance(entry, dict):
            compacted.append(entry)
            continue
        updated = dict(entry)
        result_value = updated.get("result")
        if isinstance(result_value, str) and len(result_value) > vault_threshold:
            agent_type = str(updated.get("agent_type") or "general")
            updated["result"] = _compact_result_text(
                result_value,
                workspace_path=workspace_path,
                task_index=index,
                agent_type=agent_type,
                vault_threshold=vault_threshold,
            )
            changed = True
        compacted.append(updated)

    if not changed:
        return batch_dict
    merged = dict(batch_dict)
    merged["results"] = compacted
    return merged
