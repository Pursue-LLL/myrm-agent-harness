"""Deterministic file I/O and artifact status tracker for context checkpoints.

Extracts authoritative file-read, file-modified, and artifact-creation events
directly from tool execution history and runtime trackers, eliminating LLM
hallucinations and preventing redundant full-file rereading across compactions.

[INPUT]
- langchain_core.messages::BaseMessage, AIMessage, ToolMessage
- myrm_agent_harness.agent.context_management.tracking.artifact_tracker::get_artifact_tracker, ArtifactAction

[OUTPUT]
- DeterministicFileIOSummary: Immutable dataclass capturing physical file & artifact facts
- extract_deterministic_file_io: Deterministic extractor from conversation messages
- format_file_io_markdown: Formatter generating immutable Markdown reference block

[POS]
Runtime context layer deterministic state extraction component.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

if TYPE_CHECKING:
    from collections.abc import Sequence

# Regex to normalize leading ./ or /
_NORM_PATH_RE = re.compile(r"^[./\\]+")

# Known tool action classification
_READ_TOOL_KEYWORDS = frozenset({"read", "view", "cat", "head", "tail", "grep", "inspect", "fetch"})
_WRITE_TOOL_KEYWORDS = frozenset({"write", "edit", "replace", "create", "save", "patch", "modify"})

# Argument key candidates for file paths
_PATH_ARG_KEYS = ("targetfile", "absolutepath", "filepath", "path", "file", "target", "filename", "url")


def normalize_clean_path(path: str) -> str:
    """Normalize file path for deterministic set comparison across platforms."""
    if not path:
        return ""
    cleaned = path.strip().replace("\\", "/")
    cleaned = _NORM_PATH_RE.sub("", cleaned)
    return os.path.normpath(cleaned).replace("\\", "/")


@dataclass(frozen=True)
class DeterministicFileIOSummary:
    """Immutable factual summary of file I/O operations and created artifacts."""

    files_read: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    artifacts_created: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True if no file operations or artifacts were recorded."""
        return not self.files_read and not self.files_modified and not self.artifacts_created

    def to_markdown(self) -> str:
        """Render deterministic file I/O state into an immutable Markdown block."""
        lines: list[str] = ["[Deterministic File & Artifact Manifest]"]
        if self.files_read:
            lines.append("Files Read (already inspected, do NOT reread unless modified):")
            for f in self.files_read:
                lines.append(f" - {f}")
        else:
            lines.append("Files Read: None")

        if self.files_modified:
            lines.append("Files Modified / Created:")
            for f in self.files_modified:
                lines.append(f" - {f}")
        else:
            lines.append("Files Modified: None")

        if self.artifacts_created:
            lines.append("Artifacts Created:")
            for a in self.artifacts_created:
                lines.append(f" - {a}")

        return "\n".join(lines)


def _extract_paths_from_dict(args: dict[str, object]) -> list[str]:
    """Extract candidate file paths from a tool call argument dictionary."""
    results: list[str] = []
    for k, v in args.items():
        clean_key = k.lower().replace("_", "").replace("-", "")
        if clean_key in _PATH_ARG_KEYS and isinstance(v, str) and v.strip():
            norm = normalize_clean_path(v)
            if norm and norm not in results:
                results.append(norm)
    return results


def _extract_from_tool_call(tool_name: str, args: dict[str, object]) -> tuple[list[str], list[str], list[str]]:
    """Classify tool call into reads, writes, and artifacts."""
    reads: list[str] = []
    writes: list[str] = []
    artifacts: list[str] = []

    lower_name = tool_name.lower()
    extracted_paths = _extract_paths_from_dict(args)

    is_write = any(kw in lower_name for kw in _WRITE_TOOL_KEYWORDS)
    is_read = any(kw in lower_name for kw in _READ_TOOL_KEYWORDS)

    # Check for artifact creation metadata
    if "artifactmetadata" in [k.lower().replace("_", "") for k in args]:
        for p in extracted_paths:
            artifacts.append(p)

    if is_write:
        writes.extend(extracted_paths)
    elif is_read:
        reads.extend(extracted_paths)

    return reads, writes, artifacts


def extract_deterministic_file_io(
    messages: Sequence[BaseMessage],
    chat_id: str | None = None,
) -> DeterministicFileIOSummary:
    """Extract authoritative file I/O facts from message history and runtime tracker.

    Zero LLM guessing, pure deterministic protocol parsing.
    """
    seen_reads: set[str] = set()
    ordered_reads: list[str] = []
    seen_writes: set[str] = set()
    ordered_writes: list[str] = []
    seen_artifacts: set[str] = set()
    ordered_artifacts: list[str] = []

    # 1. Integrate ArtifactTracker if available for chat_id
    if chat_id:
        try:
            from myrm_agent_harness.agent.context_management.tracking.artifact_tracker import (
                ArtifactAction,
                get_artifact_tracker,
            )

            tracker = get_artifact_tracker(chat_id)
            if tracker:
                for record in tracker.records:
                    norm = normalize_clean_path(record.path)
                    if not norm:
                        continue
                    if record.action in (ArtifactAction.CREATED, ArtifactAction.MODIFIED):
                        if norm not in seen_writes:
                            seen_writes.add(norm)
                            ordered_writes.append(norm)
                        if record.action == ArtifactAction.CREATED and norm not in seen_artifacts:
                            seen_artifacts.add(norm)
                            ordered_artifacts.append(norm)
                    elif record.action == ArtifactAction.READ:
                        if norm not in seen_reads:
                            seen_reads.add(norm)
                            ordered_reads.append(norm)
        except Exception:
            pass

    # 2. Parse AIMessage tool_calls and ToolMessages
    for msg in messages:
        if isinstance(msg, AIMessage):
            # Check structured tool calls
            tool_calls = getattr(msg, "tool_calls", None)
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        name = str(tc.get("name", ""))
                        raw_args = tc.get("args", {})
                        args = raw_args if isinstance(raw_args, dict) else {}
                        r_paths, w_paths, a_paths = _extract_from_tool_call(name, args)
                        for r in r_paths:
                            if r not in seen_reads:
                                seen_reads.add(r)
                                ordered_reads.append(r)
                        for w in w_paths:
                            if w not in seen_writes:
                                seen_writes.add(w)
                                ordered_writes.append(w)
                        for a in a_paths:
                            if a not in seen_artifacts:
                                seen_artifacts.add(a)
                                ordered_artifacts.append(a)

        elif isinstance(msg, ToolMessage):
            tool_name = (msg.name or "").lower()
            # Extract from tool message artifact or additional_kwargs
            extracted: list[str] = []
            if getattr(msg, "artifact", None) and isinstance(msg.artifact, dict):
                p = msg.artifact.get("path") or msg.artifact.get("file_path") or msg.artifact.get("target_file")
                if isinstance(p, str) and p.strip():
                    extracted.append(normalize_clean_path(p))
            if msg.additional_kwargs:
                p = (
                    msg.additional_kwargs.get("path")
                    or msg.additional_kwargs.get("file_path")
                    or msg.additional_kwargs.get("target_file")
                )
                if isinstance(p, str) and p.strip():
                    extracted.append(normalize_clean_path(p))

            is_write = any(kw in tool_name for kw in _WRITE_TOOL_KEYWORDS)
            is_read = any(kw in tool_name for kw in _READ_TOOL_KEYWORDS)

            for path_str in extracted:
                if is_write and path_str not in seen_writes:
                    seen_writes.add(path_str)
                    ordered_writes.append(path_str)
                elif is_read and path_str not in seen_reads:
                    seen_reads.add(path_str)
                    ordered_reads.append(path_str)

    return DeterministicFileIOSummary(
        files_read=ordered_reads,
        files_modified=ordered_writes,
        artifacts_created=ordered_artifacts,
    )
