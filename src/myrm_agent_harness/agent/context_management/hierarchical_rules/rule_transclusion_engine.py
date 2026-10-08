# [INPUT]: None
# [OUTPUT]: resolve_rule_transclusions, extract_transclusion_paths
# [POS]: agent/context_management/hierarchical_rules/rule_transclusion_engine.py

"""Rule transclusion engine resolving inline @path references to prevent drift.

[INPUT]
- None (Self-contained string and path resolution logic).

[OUTPUT]
- resolve_rule_transclusions: Inlines referenced markdown rules recursively with cycle prevention.
- extract_transclusion_paths: Extracts all @path references found within a document.

[POS]
Rule composition preprocessor eliminating copy-paste drift via single-source transclusions.
"""

from __future__ import annotations

import os
import re
from typing import Mapping

TRANSCLUSION_PATTERN = re.compile(r"(?<!\w)@([\w\.\/\-]+\.md)\b", re.IGNORECASE)


def extract_transclusion_paths(text: str) -> list[str]:
    """Extract all @path/to/rule.md references in order of appearance."""
    matches = TRANSCLUSION_PATTERN.findall(text)
    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def resolve_rule_transclusions(
    base_file_path: str,
    raw_content: str,
    file_reader: Mapping[str, str] | None = None,
    max_depth: int = 5,
) -> tuple[str, list[str]]:
    """Recursively resolve and inline @path references with cycle detection.

    Args:
        base_file_path: Path of the parent rule file (for relative path resolution).
        raw_content: Content containing potential @path references.
        file_reader: Optional in-memory file mock mapping {path: content}. If None, reads from disk.
        max_depth: Recursion limit guarding against excessive depth.

    Returns:
        tuple[str, list[str]]: (resolved_inlined_content, list_of_included_paths)
    """
    included_paths: list[str] = []
    visited_files: set[str] = {os.path.abspath(base_file_path)}

    def read_file_content(path: str) -> str | None:
        if file_reader is not None:
            # Check direct or relative
            if path in file_reader:
                return file_reader[path]
            for k, v in file_reader.items():
                if os.path.basename(k) == os.path.basename(path):
                    return v
            return None

        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def _resolve(
        current_path: str,
        content: str,
        depth: int,
    ) -> str:
        if depth > max_depth:
            return content

        base_dir = os.path.dirname(os.path.abspath(current_path))

        def replace_match(match: re.Match[str]) -> str:
            ref_rel_path = match.group(1)
            # Resolve target path relative to current file directory
            candidate_abs = os.path.normpath(os.path.join(base_dir, ref_rel_path))

            if candidate_abs in visited_files:
                # Cycle detected; emit inline cycle warning comment rather than looping infinitely
                return f"<!-- Transclusion cycle prevented: @{ref_rel_path} -->"

            sub_content = read_file_content(candidate_abs)
            if sub_content is None:
                # Fallback check relative to cwd or literal
                sub_content = read_file_content(ref_rel_path)

            if sub_content is None:
                # Missing reference; leave intact or note unresolvable
                return match.group(0)

            visited_files.add(candidate_abs)
            included_paths.append(ref_rel_path)

            # Strip any frontmatter from the transcluded snippet
            clean_sub = re.sub(r"^---\s*\n.*?\n---\s*\n", "", sub_content, flags=re.DOTALL)
            resolved_child = _resolve(candidate_abs, clean_sub.strip(), depth + 1)
            visited_files.remove(candidate_abs)

            banner = f"<!-- Begin transclusion: @{ref_rel_path} -->\n"
            footer = f"\n<!-- End transclusion: @{ref_rel_path} -->"
            return banner + resolved_child + footer

        return TRANSCLUSION_PATTERN.sub(replace_match, content)

    resolved = _resolve(base_file_path, raw_content, 0)
    return resolved, included_paths
