"""Read text content from Shared Artifact Vault URIs for file_read_tool.

[INPUT]
- agent.artifacts.vault::ArtifactVault, VAULT_PREFIX (POS: Shared Artifact Vault, vault:// pointer protocol)
- ..core.operation_context::ViewRange (POS: View line range for partial reads)
- ..file_read_truncation::truncate_file_output (POS: Truncation utilities shared by file_read handlers)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes)
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: workspace root resolution)

[OUTPUT]
- is_vault_uri: predicate for vault:// paths
- path_base: strip line-range suffix (vault-safe)
- resolve_workspace_root: workspace for ArtifactVault reads
- read_vault_text_content: load vault object text with optional line range and preview mode
- read_vault_paths_to_parts: batch vault reads for file_read_tool

[POS]
Vault URI reader for file_read_tool. Keeps vault:// handling out of FileOperationService.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.artifacts.vault import VAULT_PREFIX, ArtifactVault

from ..file_read_truncation import truncate_file_output
from .file_utils import parse_path_with_range

if TYPE_CHECKING:
    from myrm_agent_harness.agent.meta_tools.file_ops.core.operation_context import ViewRange
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

_PREVIEW_MAX_LINES = 1000


def is_vault_uri(path: str) -> bool:
    """Return True when *path* is a vault:// pointer (optionally with :line-range suffix)."""
    return path.startswith(VAULT_PREFIX)


def path_base(path: str) -> str:
    """Return the path without line-range suffix (vault-safe)."""
    if is_vault_uri(path):
        base, _ = parse_path_with_range(path)
        return base
    return path.split(":")[0] if ":" in path else path


def resolve_workspace_root(executor: CodeExecutor | None) -> str | None:
    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
        WorkspacePathResolver,
    )

    try:
        return str(WorkspacePathResolver.resolve_workspace_root())
    except (OSError, RuntimeError, ValueError) as exc:
        logger.debug("WorkspacePathResolver failed: %s", exc)
    if executor is not None:
        ws = getattr(executor, "_current_workspace", None) or getattr(executor, "workspace_path", None)
        if ws:
            return str(ws)
    return None


def read_vault_text_content(
    vault_uri: str,
    workspace_root: str,
    *,
    view_range: ViewRange | None = None,
    mode: str = "all",
) -> str:
    """Load UTF-8 text from a vault:// URI with optional line slicing."""
    if not vault_uri.startswith(VAULT_PREFIX):
        raise ValueError(f"Invalid vault URI: {vault_uri}")

    vault = ArtifactVault(workspace_root)
    meta = vault.get_meta(vault_uri)
    if meta is None:
        raise FileNotFoundError(f"Vault object not found or expired: {vault_uri}")

    raw_bytes = vault.get(vault_uri)
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    if view_range is not None:
        start_idx = max(view_range.start - 1, 0)
        end_idx = len(lines) if view_range.end == -1 else min(view_range.end, len(lines))
        lines = lines[start_idx:end_idx]
        text = "".join(lines)

    if mode == "preview" and len(lines) > _PREVIEW_MAX_LINES:
        preview = "".join(lines[:_PREVIEW_MAX_LINES])
        return (
            f"{preview}\n\n"
            f"...[preview mode: first {_PREVIEW_MAX_LINES} of {len(lines)} lines; "
            f"use {vault_uri}:1-{_PREVIEW_MAX_LINES} or mode='all']..."
        )

    return text


async def read_vault_paths_to_parts(
    vault_paths: list[str],
    executor: CodeExecutor | None,
    mode: str,
    *,
    config: RunnableConfig,
) -> list[str]:
    from myrm_agent_harness.utils.event_utils import dispatch_custom_event

    parts: list[str] = []
    workspace = resolve_workspace_root(executor)
    for path_str in vault_paths:
        if not workspace:
            parts.append(f"[Error: Cannot read {path_str} - workspace unavailable]")
            continue
        vault_uri, view_range = parse_path_with_range(path_str)
        try:
            content = read_vault_text_content(vault_uri, workspace, view_range=view_range, mode=mode)
            truncated, was_truncated, meta = truncate_file_output(content, path_str=path_str)
            parts.append(f"=== {path_str} ===\n{truncated}")
            if was_truncated:
                await dispatch_custom_event(
                    "agent_status",
                    {"event": "tool_truncated", "tool": "file_read", "metadata": meta},
                    config=config,
                )
        except FileNotFoundError as exc:
            parts.append(f"[Error: {exc}]")
    return parts
