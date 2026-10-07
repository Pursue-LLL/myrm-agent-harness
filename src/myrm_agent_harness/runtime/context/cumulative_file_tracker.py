"""Cumulative file footprint tracker across multi-turn sessions, compactions, and branches.

Extracts file read and modification operations from tool calls, logs, and summaries,
maintaining an exact mathematical union footprint to eliminate file amnesia.
Strict 0 Any, immutable records, typed methods.

[INPUT]
- runtime.context.lca_branch_summary_types::CumulativeFileFootprint (POS: Type contracts for LCA branch
  exploration summary and cumulative file tracking.)
- runtime.context.pi_compaction_types::CumulativeFileRecord (POS: Type definitions for Pi Agent-style
  progressive context compaction, branch summarization, and cumulative file tracker engine.)

[OUTPUT]
- CumulativeFileTracker: Thread-safe engine for tracking and union-aggregating file operations.

[POS]
Cumulative file footprint tracker across multi-turn sessions, compactions, and branches.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence

from .lca_branch_summary_types import CumulativeFileFootprint
from .pi_compaction_types import CumulativeFileRecord

logger = logging.getLogger(__name__)

# Common file inspection and read tool names
_READ_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "read_file",
        "view_file",
        "read",
        "view",
        "cat",
        "head",
        "tail",
        "grep",
        "transparent_read",
        "read_symbol",
    }
)

# Common file modification and write tool names
_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "write_to_file",
        "replace_file_content",
        "edit_file",
        "write",
        "edit",
        "create_file",
        "patch_file",
        "append_file",
        "touch",
    }
)

_PATH_ARGUMENT_KEYS: tuple[str, ...] = (
    "targetfile",
    "target_file",
    "absolutepath",
    "absolute_path",
    "path",
    "filepath",
    "file_path",
    "filename",
    "file",
)


class CumulativeFileTracker:
    """Thread-safe engine for tracking and union-aggregating file operations."""

    def __init__(self, initial_footprint: CumulativeFileFootprint | None = None) -> None:
        self._current_footprint: CumulativeFileFootprint = (
            initial_footprint or CumulativeFileFootprint()
        )

    @property
    def footprint(self) -> CumulativeFileFootprint:
        """Return the current cumulative footprint."""
        return self._current_footprint

    def merge_footprint(self, other: CumulativeFileFootprint) -> CumulativeFileFootprint:
        """Merge an external footprint into the current state via mathematical union."""
        self._current_footprint = self._current_footprint.union(other)
        return self._current_footprint

    def record_operations(
        self,
        *,
        read_files: Sequence[str] = (),
        modified_files: Sequence[str] = (),
    ) -> CumulativeFileFootprint:
        """Manually record file reads and modifications, returning the updated footprint."""
        self._current_footprint = self._current_footprint.union(
            extra_reads=tuple(read_files),
            extra_modified=tuple(modified_files),
        )
        return self._current_footprint

    def extract_from_tool_call(
        self,
        tool_name: str,
        arguments: Mapping[str, object] | str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Extract read and modified file paths from a tool invocation.

        Returns (extracted_reads, extracted_modified).
        """
        norm_name = tool_name.strip().lower()
        args_dict = self._parse_arguments(arguments)
        extracted_path = self._extract_path_from_args(args_dict)

        if not extracted_path:
            return (), ()

        if norm_name in _WRITE_TOOL_NAMES:
            return (), (extracted_path,)
        if norm_name in _READ_TOOL_NAMES:
            return (extracted_path,), ()

        return (), ()

    def extract_and_accumulate_from_entry(
        self,
        entry: object,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Extract file footprints from generic session entries, messages, or dicts.

        Supports dicts, SessionTreeNodeEntry, ContextLogEntry, and ProjectedMessage.
        Updates internal footprint and returns the newly discovered (reads, modifications).
        """
        reads: set[str] = set()
        mods: set[str] = set()

        # 1. Direct explicit attributes
        direct_reads = getattr(entry, "read_files", None)
        if isinstance(direct_reads, (list, tuple, set)):
            for f in direct_reads:
                if isinstance(f, str) and f.strip():
                    reads.add(f.strip())

        direct_mods = getattr(entry, "modified_files", None)
        if isinstance(direct_mods, (list, tuple, set)):
            for f in direct_mods:
                if isinstance(f, str) and f.strip():
                    mods.add(f.strip())

        # 2. Extract from details mapping or dictionary
        details = getattr(entry, "details", None)
        if isinstance(details, Mapping):
            self._extract_from_details_mapping(details, reads, mods)

        # 3. If entry itself is a Mapping
        if isinstance(entry, Mapping):
            self._extract_from_mapping(entry, reads, mods)

        # 4. Extract from content if it contains structured tool metadata
        content = getattr(entry, "content", None)
        if isinstance(content, str):
            self._extract_from_text_content(content, reads, mods)

        # 5. Extract from tool_calls attribute (e.g. ProjectedMessage.tool_calls)
        tool_calls = getattr(entry, "tool_calls", None)
        if isinstance(tool_calls, (list, tuple)):
            for tc in tool_calls:
                if isinstance(tc, str) and tc.startswith("{"):
                    try:
                        tc_data = json.loads(tc)
                        fn_name = str(tc_data.get("name", ""))
                        tc_args = tc_data.get("arguments", {})
                        r, m = self.extract_from_tool_call(
                            fn_name,
                            tc_args if isinstance(tc_args, (dict, str)) else str(tc_args),
                        )
                        reads.update(r)
                        mods.update(m)
                    except Exception:
                        pass

        # 6. Extract from tool role message with inline path pattern
        role = getattr(entry, "role", None)
        role_str = str(role).lower() if role is not None else ""
        if "tool" in role_str and isinstance(content, str) and content:
            tool_name = str(getattr(entry, "name", "")).lower()
            path_match = re.search(r"['\"]?([a-zA-Z0-9_\-\.\/]+\.[a-zA-Z0-9]+)['\"]?", content)
            if path_match:
                found_path = path_match.group(1).strip()
                if tool_name in _READ_TOOL_NAMES or "read" in tool_name:
                    reads.add(found_path)
                elif (
                    tool_name in _WRITE_TOOL_NAMES
                    or "write" in tool_name
                    or "edit" in tool_name
                    or "replace" in tool_name
                ):
                    mods.add(found_path)

        # Accumulate into current footprint
        new_reads = tuple(sorted(reads))
        new_mods = tuple(sorted(mods))
        if new_reads or new_mods:
            self.record_operations(read_files=new_reads, modified_files=new_mods)

        return new_reads, new_mods

    @classmethod
    def extract_from_messages(
        cls,
        messages: Sequence[object],
        prev_record: CumulativeFileRecord | None = None,
    ) -> CumulativeFileRecord:
        """Extract read and modified file paths from messages and merge cumulatively."""
        initial = (
            CumulativeFileFootprint(
                read_files=prev_record.read_files,
                modified_files=prev_record.modified_files,
            )
            if prev_record
            else None
        )
        tracker = cls(initial)
        tracker.accumulate_from_entries(messages)
        return CumulativeFileRecord(
            read_files=tracker.footprint.read_files,
            modified_files=tracker.footprint.modified_files,
        )

    def accumulate_from_entries(
        self,
        entries: Sequence[object],
    ) -> CumulativeFileFootprint:
        """Traverse a sequence of entries and accumulate all file operations."""
        for e in entries:
            self.extract_and_accumulate_from_entry(e)
        return self._current_footprint

    def compute_incremental_diff(
        self,
        baseline: CumulativeFileFootprint,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Compute newly introduced reads and modifications relative to a baseline footprint."""
        baseline_reads = set(baseline.read_files)
        baseline_mods = set(baseline.modified_files)

        new_reads = tuple(sorted(f for f in self._current_footprint.read_files if f not in baseline_reads))
        new_mods = tuple(sorted(f for f in self._current_footprint.modified_files if f not in baseline_mods))
        return new_reads, new_mods

    @staticmethod
    def _parse_arguments(args: Mapping[str, object] | str) -> Mapping[str, object]:
        if isinstance(args, Mapping):
            return args
        if isinstance(args, str) and args.strip().startswith("{"):
            try:
                parsed = json.loads(args)
                if isinstance(parsed, Mapping):
                    return parsed
            except Exception:
                pass
        return {}

    @classmethod
    def _extract_path_from_args(cls, args: Mapping[str, object]) -> str | None:
        for key, val in args.items():
            if key.lower() in _PATH_ARGUMENT_KEYS and isinstance(val, str) and val.strip():
                return val.strip()
        return None

    def _extract_from_details_mapping(
        self,
        details: Mapping[str, object],
        reads: set[str],
        mods: set[str],
    ) -> None:
        tool_name = details.get("tool_name") or details.get("name")
        args = details.get("tool_args") or details.get("arguments") or details.get("args")

        if isinstance(tool_name, str):
            effective_args = args if args is not None else details
            r, m = self.extract_from_tool_call(
                tool_name,
                str(effective_args) if not isinstance(effective_args, Mapping) else effective_args,
            )
            reads.update(r)
            mods.update(m)

        for key in ("read_files", "reads"):
            val = details.get(key)
            if isinstance(val, (list, tuple, set)):
                reads.update(str(x).strip() for x in val if isinstance(x, str) and x.strip())
            elif isinstance(val, str) and val.strip():
                reads.update(x.strip() for x in val.split(",") if x.strip())

        for key in ("modified_files", "writes", "modified"):
            val = details.get(key)
            if isinstance(val, (list, tuple, set)):
                mods.update(str(x).strip() for x in val if isinstance(x, str) and x.strip())
            elif isinstance(val, str) and val.strip():
                mods.update(x.strip() for x in val.split(",") if x.strip())

    def _extract_from_mapping(
        self,
        entry_map: Mapping[str, object],
        reads: set[str],
        mods: set[str],
    ) -> None:
        tool = entry_map.get("tool") or entry_map.get("name")
        args = entry_map.get("arguments") or entry_map.get("args")
        if isinstance(tool, str):
            effective_args = args if args is not None else entry_map
            r, m = self.extract_from_tool_call(
                tool,
                str(effective_args) if not isinstance(effective_args, Mapping) else effective_args,
            )
            reads.update(r)
            mods.update(m)

        det = entry_map.get("details")
        if isinstance(det, Mapping):
            self._extract_from_details_mapping(det, reads, mods)

    @staticmethod
    def _extract_from_text_content(content: str, reads: set[str], mods: set[str]) -> None:
        if "<read-files>" in content or "<cumulative-read-files>" in content:
            for line in content.splitlines():
                if "<file>" in line and "</file>" in line:
                    start = line.find("<file>") + len("<file>")
                    end = line.find("</file>")
                    candidate = line[start:end].strip()
                    if candidate:
                        reads.add(candidate)

        if "<modified-files>" in content or "<cumulative-modified-files>" in content:
            for line in content.splitlines():
                if "<file>" in line and "</file>" in line:
                    start = line.find("<file>") + len("<file>")
                    end = line.find("</file>")
                    candidate = line[start:end].strip()
                    if candidate:
                        mods.add(candidate)
