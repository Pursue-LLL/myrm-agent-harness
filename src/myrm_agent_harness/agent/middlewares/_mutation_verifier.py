"""Per-turn file mutation verifier.

Tracks file-mutating tool call outcomes within a single agent turn.
At turn-end, surfaces any failed mutations as a structured event so
the frontend can display a warning banner — preventing the model from
"over-claiming" successful edits while files remain unchanged on disk.

[INPUT]
- None (Self-contained ContextVar state)

[OUTPUT]
- record_mutation_result: Record success/failure after a file-mutating tool call
- get_failed_mutations: Retrieve current turn's failed mutation dict
- reset_mutation_state: Clear state at turn start
- format_mutation_failures: Format failures into an event payload

[POS]
Per-turn file mutation verifier. Prevents model hallucination of successful
file edits by tracking actual tool outcomes and surfacing failures as SSE events.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# File-mutating tool names tracked by this verifier
_FILE_MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "file_write_tool",
        "file_edit_tool",
    }
)

# Per-turn state: {normalized_path: {tool: str, error_preview: str}}
_mutation_state_var: ContextVar[dict[str, dict[str, str]]] = ContextVar("mutation_verifier_state")

# Max files shown in the failure summary (prevents flooding)
_MAX_DISPLAY_FILES = 10


def reset_mutation_state() -> None:
    """Reset the per-turn state. Call at the start of each agent turn."""
    _mutation_state_var.set({})


def record_mutation_result(
    tool_name: str,
    tool_args: dict[str, Any],
    is_error: bool,
    error_content: str | None = None,
) -> None:
    """Record a file-mutating tool call outcome.

    On failure: stores {path: {tool, error_preview}}, keeping the first error.
    On success: removes any prior failure for the same path (model self-healed).
    """
    if tool_name not in _FILE_MUTATING_TOOLS:
        return

    state = _mutation_state_var.get(None)
    if state is None:
        return

    path = _extract_path(tool_name, tool_args)
    if not path:
        return

    if is_error:
        # Keep the FIRST error — repeated failures shouldn't mask root cause
        if path not in state:
            preview = _truncate_error(error_content) if error_content else ""
            state[path] = {"tool": tool_name, "error_preview": preview}
    else:
        # Success clears prior failure (model recovered within the turn)
        state.pop(path, None)


def get_failed_mutations() -> dict[str, dict[str, str]]:
    """Return the current turn's failed mutations. Empty dict if none."""
    return _mutation_state_var.get(None) or {}


def format_mutation_failures() -> dict[str, Any] | None:
    """Format failed mutations into a structured event payload.

    Returns None if no failures exist.
    """
    failed = get_failed_mutations()
    if not failed:
        return None

    files = []
    items = list(failed.items())
    for path, info in items[:_MAX_DISPLAY_FILES]:
        files.append(
            {
                "path": path,
                "tool": info["tool"],
                "error_preview": info["error_preview"],
            }
        )

    payload: dict[str, Any] = {
        "failed_count": len(failed),
        "files": files,
    }

    if len(failed) > _MAX_DISPLAY_FILES:
        payload["truncated"] = len(failed) - _MAX_DISPLAY_FILES

    return payload


def _extract_path(tool_name: str, args: dict[str, Any]) -> str | None:
    """Extract the target file path from tool arguments."""
    path = args.get("path")
    if isinstance(path, str) and path.strip():
        return path.strip()
    return None


def _truncate_error(content: str | None, max_len: int = 200) -> str:
    """Truncate error content for preview, preserving useful information."""
    if not content:
        return ""
    text = content.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"
