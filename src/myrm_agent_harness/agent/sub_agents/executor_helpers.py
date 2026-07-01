"""Subagent executor helper functions.

[INPUT]
- .types::SubagentConfig, AgentHandoverState (POS: Subagent subsystem core type definitions.)
- .builder::truncate_result (POS: Subagent construction helpers — tool filtering via DelegationCapabilityManifest, model resolution, token merge.)
- agent.artifacts.vault::ArtifactVault (POS: Shared Artifact Vault, vault:// pointer protocol)
- agent.artifacts::infer_artifact_type_from_extension, push_inline_artifact (POS: Inline artifact SSE queue for frontend delivery)

[OUTPUT]
- _filter_fork_messages, _estimate_msg_tokens: fork context filtering
- _cascade_cancel_descendants: cascade cancellation
- _compact_error_message, _auto_vault_or_truncate: oversized result vault (parent workspace under ISOLATED_COPY), inline artifact, file_read_tool recovery hint
- _parse_handover_state: handover block parsing

[POS]
Pure helper functions for SubagentExecutor mixins and external callers.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.artifacts import (
    infer_artifact_type_from_extension,
    push_inline_artifact,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .builder import truncate_result
from .types import AgentHandoverState, SubagentConfig

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)

# ---------------------------------------------------------------------------
# Fork context filtering
# ---------------------------------------------------------------------------


def _filter_fork_messages(
    raw_msgs: list[object],
    max_fork_tokens: int | None = None,
) -> list[object]:
    """Apply conclusion-oriented filtering for fork mode context inheritance.

    Keeps SystemMessage and HumanMessage verbatim.  For AIMessage, strips
    ``tool_calls`` / ``additional_kwargs["tool_calls"]`` so the child never
    sees orphaned function-call metadata; messages that become empty after
    stripping are dropped entirely.  All ToolMessage instances are removed
    because the child has its own tool set and doesn't need the parent's
    tool results.

    When *max_fork_tokens* is set, the filtered list is truncated from the
    oldest messages (preserving the leading SystemMessage) so the total
    estimated token count stays within budget.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    filtered: list[object] = []
    for msg in raw_msgs:
        if isinstance(msg, (SystemMessage, HumanMessage)):
            filtered.append(msg)
        elif isinstance(msg, AIMessage):
            content = msg.content
            if not content or (isinstance(content, str) and not content.strip()):
                continue
            cleaned = AIMessage(content=content)
            filtered.append(cleaned)
        elif isinstance(msg, ToolMessage):
            continue
        else:
            filtered.append(msg)

    if max_fork_tokens is not None and max_fork_tokens > 0 and len(filtered) > 1:
        total = sum(_estimate_msg_tokens(m) for m in filtered)
        while total > max_fork_tokens and len(filtered) > 1:
            if isinstance(filtered[0], SystemMessage):
                removed = filtered.pop(1)
            else:
                removed = filtered.pop(0)
            total -= _estimate_msg_tokens(removed)

    return filtered


def _estimate_msg_tokens(msg: object) -> int:
    """Rough token estimate: ~4 chars per token."""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return max(len(content) // 4, 1)
    if isinstance(content, list):
        return max(sum(len(str(c)) for c in content) // 4, 1)
    return 1


# ---------------------------------------------------------------------------
# Cascade cancellation
# ---------------------------------------------------------------------------


def _cascade_cancel_descendants(child_agent: BaseAgent | None) -> None:
    """Cancel all descendant subagents when a child agent is cancelled.

    Without this, grandchild tasks spawned by an orchestrator-role child
    would continue running (and consuming tokens) after their parent is
    cancelled, since asyncio.Task.cancel() does not propagate to sibling
    tasks created via create_task().
    """
    if child_agent is None:
        return
    try:
        cancelled = child_agent.cancel_all_children()
        if cancelled > 0:
            logger.info(
                "[subagent] Cascade-cancelled %d descendant task(s)",
                cancelled,
            )
    except Exception:
        logger.debug("[subagent] Cascade cancel failed", exc_info=True)


# ---------------------------------------------------------------------------
# Result post-processing helpers
# ---------------------------------------------------------------------------

_SUMMARY_HEAD_CHARS = 2000
_SUMMARY_TAIL_CHARS = 1000

_ERROR_HEAD_RATIO = 0.6


def _compact_error_message(error_str: str, max_chars: int) -> str:
    """Compact an oversized error string to head + truncation marker + tail.

    Preserves the error type and core message at the head, and the most
    relevant stack frames at the tail, preventing long tracebacks from
    polluting the parent agent's context window.
    """
    if max_chars <= 0 or len(error_str) <= max_chars:
        return error_str
    head_len = int(max_chars * _ERROR_HEAD_RATIO)
    tail_len = max_chars - head_len
    skipped = len(error_str) - head_len - tail_len
    marker = f"\n... [{skipped} chars truncated] ...\n"
    head_budget = max_chars - tail_len - len(marker)
    if head_budget <= 0:
        return error_str[:max_chars]
    return f"{error_str[:head_budget]}{marker}{error_str[-tail_len:]}"


def _auto_vault_or_truncate(
    raw_result: str,
    config: SubagentConfig,
    context: dict[str, object],
    task_id: str,
    agent_type: str,
) -> str:
    """Store oversized subagent output in ArtifactVault; fall back to truncation.

    When ``config.auto_vault_threshold`` is set and the result exceeds it,
    the full output is persisted to the vault and a compact summary with a
    ``vault://`` pointer is returned so the parent agent (and frontend)
    can reference it without inflating context. Also queues an inline artifact
    event when ArtifactContext is active so the vault card appears in the UI.

    For ``ISOLATED_COPY`` subagents, vault objects are stored under
    ``_isolated_parent_workspace`` so the parent agent and GUI can read them.
    """
    threshold = config.auto_vault_threshold
    if threshold is None or len(raw_result) <= threshold:
        return truncate_result(raw_result, config.max_result_tokens)

    workspace_path = context.get("workspace_path")
    if not workspace_path or not isinstance(workspace_path, str):
        logger.debug("[subagent:%s] No workspace_path - falling back to truncation", task_id)
        return truncate_result(raw_result, config.max_result_tokens)

    parent_workspace = context.get("_isolated_parent_workspace")
    vault_workspace = (
        parent_workspace
        if isinstance(parent_workspace, str) and parent_workspace
        else workspace_path
    )

    try:
        from myrm_agent_harness.agent.artifacts.vault import ArtifactVault

        vault = ArtifactVault(vault_workspace)
        vault_filename = f"subagent_{task_id}.md"
        pointer = vault.put(
            raw_result,
            vault_filename,
            "text/markdown",
            f"{agent_type} task result ({len(raw_result)} chars)",
        )

        try:
            push_inline_artifact(
                filename=vault_filename,
                preview_url=pointer,
                artifact_type=infer_artifact_type_from_extension(vault_filename),
                content_type="text/markdown",
            )
        except Exception as inner_exc:
            logger.warning(
                "[subagent:%s] Failed to push inline artifact for vault pointer %s: %s",
                task_id,
                pointer,
                inner_exc,
            )

        head = raw_result[:_SUMMARY_HEAD_CHARS]
        tail_start = max(_SUMMARY_HEAD_CHARS, len(raw_result) - _SUMMARY_TAIL_CHARS)
        tail = raw_result[tail_start:]
        omitted = tail_start - _SUMMARY_HEAD_CHARS

        if omitted > 0:
            summary = f"{head}\n\n... ({omitted} chars omitted) ...\n\n{tail}"
        else:
            summary = head

        logger.info(
            "[subagent:%s] Result auto-vaulted (%d chars → %s)",
            task_id,
            len(raw_result),
            pointer,
        )
        return (
            f"{summary}\n\n[Full result stored in vault: {pointer}]\n"
            f'To read full content: file_read_tool(paths=["{pointer}"])'
        )
    except Exception:
        logger.warning(
            "[subagent:%s] Auto-vault failed, falling back to truncation",
            task_id,
            exc_info=True,
        )
        return truncate_result(raw_result, config.max_result_tokens)


def _parse_handover_state(raw_result: str, task_id: str) -> AgentHandoverState | None:
    """Extract ``<handover>...</handover>`` JSON block from raw subagent output."""
    match = re.search(r"<handover>(.*?)</handover>", raw_result, re.DOTALL | re.IGNORECASE)
    if not match:
        return None

    try:
        json_str = match.group(1).strip()
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        elif json_str.startswith("```"):
            json_str = json_str[3:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]
        json_str = json_str.strip()

        data = json.loads(json_str)
        return AgentHandoverState.from_dict(data)
    except Exception as e:
        logger.warning("[subagent:%s] Failed to parse handover state: %s", task_id, e)
        return None
