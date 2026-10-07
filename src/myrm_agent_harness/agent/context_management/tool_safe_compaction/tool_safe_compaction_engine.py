"""Engine for tool-safe context compaction and structured file manifests transmission.

[INPUT]
- agent.context_management.tool_safe_compaction.safe_cut_point_detector::evaluate_cut_point,
  select_optimal_safe_cut_point (POS: Detects safe compaction boundaries ensuring tool_call and tool_result
  pairs remain intact.)
- agent.context_management.tool_safe_compaction.tool_safe_compaction_types::FileManifests,
  SafeCompactionResult (POS: Data contracts for safe cut-point selection, file manifests extraction, and atomic
  tool compaction.)

[OUTPUT]
- extract_file_manifests: Scan compressed turns to extract read and modified file paths.
- ToolSafeCompactionEngine: Orchestrates boundary detection, file manifest extraction, and compaction.

[POS]
Main compaction engine guaranteeing atomic tool-call safety and lossless file manifest survival.
"""

from __future__ import annotations

import logging
import re
from typing import Mapping, Sequence

from .safe_cut_point_detector import evaluate_cut_point, select_optimal_safe_cut_point
from .tool_safe_compaction_types import FileManifests, SafeCompactionResult

logger = logging.getLogger(__name__)

# Pattern detecting file paths touched in tool invocations or payloads
_FILE_PATH_PATTERN = re.compile(
    r"(?:(?:read|view|edit|write|path|file)[:=]\s*|[\"'])([\w\-./\\]+\.[a-zA-Z0-9_]+)[\"']?",
    re.IGNORECASE,
)


def extract_file_manifests(
    compressed_messages: Sequence[Mapping[str, str]],
) -> FileManifests:
    """Extract all read and modified file paths touched in the compressed message turns.

    Ensures the model retains explicit memory of touched files post-compaction,
    avoiding file re-read churn or conflicting overwrites.
    """
    read_files_set: set[str] = set()
    modified_files_set: set[str] = set()

    for msg in compressed_messages:
        content = msg.get("content", "")
        role = msg.get("role", "")
        tool_name = msg.get("tool_name", "")

        # Check explicit metadata fields
        if "read_files" in msg:
            for f in msg["read_files"].split(","):
                clean = f.strip()
                if clean:
                    read_files_set.add(clean)
        if "modified_files" in msg:
            for f in msg["modified_files"].split(","):
                clean = f.strip()
                if clean:
                    modified_files_set.add(clean)

        # Infer from tool_name and content regex
        t_lower = tool_name.lower()
        if "read" in t_lower or "view" in t_lower or "cat" in t_lower:
            for m in _FILE_PATH_PATTERN.finditer(content):
                read_files_set.add(m.group(1))
        elif "write" in t_lower or "edit" in t_lower or "replace" in t_lower or "patch" in t_lower:
            for m in _FILE_PATH_PATTERN.finditer(content):
                modified_files_set.add(m.group(1))

    return FileManifests(
        read_files=tuple(sorted(read_files_set)),
        modified_files=tuple(sorted(modified_files_set)),
    )


class ToolSafeCompactionEngine:
    """Compacts conversation history while preserving atomic tool boundaries and file manifests."""

    def __init__(self) -> None:
        self._history_results: list[SafeCompactionResult] = []

    def compact_context(
        self,
        messages: Sequence[Mapping[str, str]],
        desired_cut_index: int,
        custom_summary: str | None = None,
    ) -> SafeCompactionResult:
        """Execute atomic-safe compaction on messages up to the desired index.

        Automatically snaps to the nearest valid cut point to avoid splitting
        tool_call and tool_result pairs, extracts touched file manifests, and
        prepends a consolidated checkpoint header to the preserved tail.
        """
        if not messages:
            return SafeCompactionResult(
                cut_point_index=0,
                compressed_messages_count=0,
                preserved_messages_count=0,
                file_manifests=FileManifests(),
                compaction_summary="",
                compacted_context=(),
            )

        # 1. Determine optimal safe boundary
        safe_cut_index = select_optimal_safe_cut_point(messages, desired_cut_index)

        # 2. Slice prefix (compressed) and suffix (preserved)
        compressed_slice = messages[:safe_cut_index]
        preserved_slice = messages[safe_cut_index:]

        # 3. Extract file manifests from the compressed portion
        manifests = extract_file_manifests(compressed_slice)

        # 4. Synthesize summary with file manifests
        base_summary = custom_summary or self._synthesize_fallback_summary(compressed_slice)
        manifest_lines: list[str] = [base_summary]
        if manifests.read_files or manifests.modified_files:
            manifest_lines.append("\n[Workspace File Manifests (Survives Compaction)]")
            if manifests.read_files:
                manifest_lines.append(f"- **Files Read**: {', '.join(manifests.read_files)}")
            if manifests.modified_files:
                manifest_lines.append(f"- **Files Modified**: {', '.join(manifests.modified_files)}")

        final_summary_text = "\n".join(manifest_lines)

        # 5. Formulate final compacted message list
        # Prepend the system compaction checkpoint
        checkpoint_msg: dict[str, str] = {
            "role": "system",
            "content": f"[Context Compacted]\n{final_summary_text}",
        }

        compacted_context: list[dict[str, str]] = [checkpoint_msg]
        for msg in preserved_slice:
            compacted_context.append(dict(msg))

        result = SafeCompactionResult(
            cut_point_index=safe_cut_index,
            compressed_messages_count=len(compressed_slice),
            preserved_messages_count=len(preserved_slice),
            file_manifests=manifests,
            compaction_summary=final_summary_text,
            compacted_context=tuple(compacted_context),
        )

        self._history_results.append(result)
        logger.info(
            "Compacted %d messages (snapped %d -> %d), preserved %d messages, touched %d files",
            len(compressed_slice),
            desired_cut_index,
            safe_cut_index,
            len(preserved_slice),
            manifests.total_touched_files,
        )
        return result

    def _synthesize_fallback_summary(
        self,
        compressed_messages: Sequence[Mapping[str, str]],
    ) -> str:
        """Synthesize a concise summary from compressed turns when none is supplied."""
        if not compressed_messages:
            return "No historical turns were compressed."

        user_prompts: list[str] = []
        assistant_decisions: list[str] = []

        for msg in compressed_messages:
            role = msg.get("role", "")
            content = msg.get("content", "").strip()
            first_line = content.splitlines()[0][:100] if content else ""

            if role == "user" and first_line:
                user_prompts.append(first_line)
            elif role == "assistant" and any(
                kw in content.lower() for kw in ("decided", "completed", "implemented", "resolved")
            ):
                assistant_decisions.append(first_line)

        summary_parts = [f"Archived {len(compressed_messages)} earlier conversation turns."]
        if user_prompts:
            summary_parts.append(f"Goals explored: {'; '.join(user_prompts[:3])}")
        if assistant_decisions:
            summary_parts.append(f"Key outcomes: {'; '.join(assistant_decisions[:3])}")

        return " ".join(summary_parts)
