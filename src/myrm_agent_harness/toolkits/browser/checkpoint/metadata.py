"""Checkpoint metadata structure for browser tasks.

Extends LangGraph's checkpoint metadata with browser-specific state for O(1) recovery access.


[INPUT]
- typing::TypedDict (POS: typed dict base class)

[OUTPUT]
- CheckpointMetadata: Browser task metadata structure
- extract_metadata_from_messages(): Parse metadata from LangGraph message history

[POS]
Checkpoint metadata module. Defines browser task state stored in LangGraph checkpoint metadata,
supporting O(1) access to key info (current_url, session_domain, counters) without parsing full history.
"""

from __future__ import annotations

import re
from typing import TypedDict

# LangGraph serialized message: keys are "role", "content", "type", etc.
SerializedMessage = dict[str, object]


class CheckpointMetadata(TypedDict, total=False):
    """Extended checkpoint metadata for browser tasks.

    Stored in LangGraph checkpoint.metadata for O(1) access during recovery.
    All fields are optional to support gradual adoption.

    Attributes:
        current_url: Last navigated URL (for session reconstruction)
        session_domain: Domain for Session Vault (for session restoration)
        task_counters: Task-level counters (snapshots, interactions, navigations)
        session_hash: Hash of Session Vault state (for incremental saving)
        last_checkpoint_at: Unix timestamp of last checkpoint
        recovery_count: Number of times this task has been recovered
    """

    current_url: str
    session_domain: str
    task_counters: dict[str, int]
    session_hash: str
    last_checkpoint_at: float
    recovery_count: int


def _extract_url_from_content(content: str) -> str | None:
    """Extract URL from message content.

    Args:
        content: Message content string

    Returns:
        Extracted URL or None if not found
    """
    # Try snapshot metadata header
    snapshot_pattern = re.compile(r"\[.*?\|\s*~?\d+\s*tokens\s*\|.*?url:\s*([^\]]+)\]")
    match = snapshot_pattern.search(content)
    if match:
        return match.group(1).strip()

    # Try navigation call
    navigate_pattern = re.compile(r'browser_navigate.*?url["\']?\s*[:=]\s*["\']([^"\']+)', re.IGNORECASE)
    match = navigate_pattern.search(content)
    if match:
        return match.group(1).strip()

    return None


def _extract_session_domain_from_content(content: str) -> str | None:
    """Extract session domain from message content.

    Args:
        content: Message content string

    Returns:
        Extracted session domain or None if not found
    """
    session_pattern = re.compile(
        r'(?:save|restore|delete)_session.*?domain["\']?\s*[:=]\s*["\']([^"\']+)', re.IGNORECASE
    )
    match = session_pattern.search(content)
    return match.group(1).strip() if match else None


def _count_operations_in_content(content: str) -> tuple[int, int, int]:
    """Count browser operations in message content.

    Args:
        content: Message content string

    Returns:
        Tuple of (snapshot_count, interaction_count, navigation_count)
    """
    snapshot_count = 0
    interaction_count = 0
    navigation_count = 0

    if "browser_snapshot_tool" in content or ("[" in content and "refs" in content):
        snapshot_count = 1

    if "browser_interact_tool" in content or any(action in content for action in ["click", "type", "fill"]):
        interaction_count = 1

    if "browser_navigate_tool" in content or "Navigated to" in content:
        navigation_count = 1

    return snapshot_count, interaction_count, navigation_count


def extract_metadata_from_messages(messages: list[SerializedMessage]) -> CheckpointMetadata:
    """Extract checkpoint metadata from LangGraph message history.

    Fallback parser for when metadata is not directly available in checkpoint.metadata.
    Scans messages in reverse chronological order for efficiency.

    Args:
        messages: LangGraph message history

    Returns:
        Extracted metadata with available fields populated

    Raises:
        ValueError: If messages list is empty
    """
    if not messages:
        raise ValueError("Cannot extract metadata from empty message history")

    metadata: CheckpointMetadata = {}

    snapshot_count = 0
    interaction_count = 0
    navigation_count = 0

    # Scan messages in reverse (most recent first)
    for msg in reversed(messages):
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue

        # Extract current_url (only once)
        if "current_url" not in metadata:
            url = _extract_url_from_content(content)
            if url:
                metadata["current_url"] = url

        # Extract session_domain (only once)
        if "session_domain" not in metadata:
            domain = _extract_session_domain_from_content(content)
            if domain:
                metadata["session_domain"] = domain

        # Count operations
        snap, interact, nav = _count_operations_in_content(content)
        snapshot_count += snap
        interaction_count += interact
        navigation_count += nav

    # Populate counters
    if snapshot_count > 0 or interaction_count > 0 or navigation_count > 0:
        metadata["task_counters"] = {
            "snapshots": snapshot_count,
            "interactions": interaction_count,
            "navigations": navigation_count,
        }

    return metadata


def merge_metadata(
    base: CheckpointMetadata | None,
    update: CheckpointMetadata | None,
) -> CheckpointMetadata:
    """Merge two metadata dictionaries (update takes precedence).

    Args:
        base: Base metadata
        update: Update metadata

    Returns:
        Merged metadata
    """
    if base is None:
        return update or {}
    if update is None:
        return base

    merged = dict(base)
    merged.update(update)

    # Deep merge for task_counters
    if "task_counters" in base and "task_counters" in update:
        base_counters = base["task_counters"]
        update_counters = update["task_counters"]
        merged["task_counters"] = {**base_counters, **update_counters}

    return merged
