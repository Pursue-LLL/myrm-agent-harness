"""Patch application system for skill evolution.

Supports LLM output formats:
- FULL: Complete single-file content
- DIFF: SEARCH/REPLACE blocks (uses 7-level progressive fuzzy matching)
- MULTI_FILE_FULL: Complete multi-file content (*** Begin Files / *** File: format)

[INPUT]
- (none)

[OUTPUT]
- PatchType: LLM output format for skill edits.
- SkillPatchResult: Result of patch application.
- PatchError: Raised when patch cannot be applied.
- detect_patch_type: Auto-detect patch format from LLM output.
- apply_skill_patch: Apply LLM output to skill content.

[POS]
Patch application system for skill evolution.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum

from myrm_agent_harness.utils.fuzzy_match import fuzzy_find

logger = logging.getLogger(__name__)

__all__ = [
    "PatchType",
    "SkillPatchResult",
    "apply_skill_patch",
    "detect_patch_type",
    "parse_multi_file_full",
]

SKILL_FILENAME = "SKILL.md"

_MULTI_FILE_MARKER_RE = re.compile(r"^\*{3}\s*(?:File|Begin Files)\s*", re.MULTILINE)
_FILE_HEADER_RE = re.compile(r"^\*{3}\s*File:\s*(.+?)\s*$", re.MULTILINE)


class PatchType(StrEnum):
    """LLM output format for skill edits."""

    AUTO = "auto"
    FULL = "full"
    DIFF = "diff"
    MULTI_FILE_FULL = "multi_file_full"


@dataclass
class SkillPatchResult:
    """Result of patch application."""

    success: bool
    content: str = ""
    error_message: str = ""
    num_changes_applied: int = 0
    auxiliary_files: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.success


class PatchError(RuntimeError):
    """Raised when patch cannot be applied."""

    pass


# SEARCH/REPLACE block pattern
SEARCH_REPLACE_PATTERN = re.compile(r"<{7}\s*SEARCH\s*\n(.*?)\n\s*={7}\s*\n(.*?)\n\s*>{7}\s*REPLACE\s*", re.DOTALL)


def detect_patch_type(content: str) -> PatchType:
    """Auto-detect patch format from LLM output.

    Detection order (by specificity):
    1. *** File: / *** Begin Files → MULTI_FILE_FULL
    2. <<<<<<< SEARCH → DIFF (SEARCH/REPLACE blocks)
    3. Default → FULL (complete content)

    Args:
        content: LLM output string

    Returns:
        Detected PatchType
    """
    if _MULTI_FILE_MARKER_RE.search(content):
        return PatchType.MULTI_FILE_FULL
    if "<<<<<<< SEARCH" in content:
        return PatchType.DIFF
    return PatchType.FULL


def apply_skill_patch(
    original_content: str, llm_output: str, patch_type: PatchType = PatchType.AUTO
) -> SkillPatchResult:
    """Apply LLM output to skill content.

    Args:
        original_content: Current skill content
        llm_output: LLM-generated patch/content
        patch_type: Format type (AUTO to auto-detect)

    Returns:
        SkillPatchResult with updated content or error
    """
    if patch_type == PatchType.AUTO:
        patch_type = detect_patch_type(llm_output)

    try:
        if patch_type == PatchType.MULTI_FILE_FULL:
            return _apply_multi_file_full(llm_output)
        if patch_type == PatchType.DIFF:
            return _apply_search_replace(original_content, llm_output)
        return _apply_full_content(llm_output)
    except PatchError as e:
        return SkillPatchResult(success=False, error_message=str(e))
    except Exception as e:
        return SkillPatchResult(success=False, error_message=f"Unexpected error: {e}")


def parse_multi_file_full(llm_output: str) -> dict[str, str]:
    """Parse ``*** File: <path>`` blocks into ``{relative_path: content}``.

    Format example::

        *** File: SKILL.md
        (SKILL.md content)
        *** File: scripts/post.ts
        (script content)

    Args:
        llm_output: LLM output containing *** File: headers

    Returns:
        Dict mapping relative paths to file contents.
        Empty dict if no valid blocks found.
    """
    headers = list(_FILE_HEADER_RE.finditer(llm_output))
    if not headers:
        return {}

    files: dict[str, str] = {}
    for i, match in enumerate(headers):
        filepath = match.group(1).strip()
        content_start = match.end()
        content_end = headers[i + 1].start() if i + 1 < len(headers) else len(llm_output)
        content = llm_output[content_start:content_end].strip("\n")
        if filepath:
            files[filepath] = content

    return files


def _apply_multi_file_full(llm_output: str) -> SkillPatchResult:
    """Apply MULTI_FILE_FULL format (multiple complete files).

    Parses ``*** File:`` blocks, extracts SKILL.md as primary content
    and remaining files as auxiliary_files.

    Args:
        llm_output: LLM output with *** File: headers

    Returns:
        SkillPatchResult with content (SKILL.md) and auxiliary_files
    """
    files = parse_multi_file_full(llm_output)
    if not files:
        return SkillPatchResult(success=False, error_message="No *** File: blocks found in multi-file output")

    skill_content = files.pop(SKILL_FILENAME, "")
    if not skill_content:
        # Try case-insensitive fallback
        for key in list(files.keys()):
            if key.lower() == SKILL_FILENAME.lower():
                skill_content = files.pop(key)
                break

    if not skill_content:
        return SkillPatchResult(success=False, error_message=f"Multi-file output missing {SKILL_FILENAME}")

    return SkillPatchResult(
        success=True, content=skill_content, auxiliary_files=files, num_changes_applied=1 + len(files)
    )


def _apply_full_content(llm_output: str) -> SkillPatchResult:
    """Apply FULL format (complete content replacement).

    Args:
        llm_output: Complete new skill content

    Returns:
        SkillPatchResult with new content
    """
    content = llm_output.strip()
    if not content:
        return SkillPatchResult(success=False, error_message="Empty FULL content")

    return SkillPatchResult(success=True, content=content, num_changes_applied=1)


def _apply_search_replace(original: str, llm_output: str) -> SkillPatchResult:
    """Apply DIFF format (SEARCH/REPLACE blocks with fuzzy matching).

    Uses 7-level fuzzy matching chain for progressive match degradation.

    Args:
        original: Original skill content
        llm_output: LLM output with SEARCH/REPLACE blocks

    Returns:
        SkillPatchResult with patched content

    Raises:
        PatchError: When SEARCH block not found or no blocks present
    """
    blocks = list(SEARCH_REPLACE_PATTERN.finditer(llm_output))

    if not blocks:
        return SkillPatchResult(success=False, error_message="No SEARCH/REPLACE blocks found in LLM output")

    updated_content = original
    num_applied = 0

    for i, block in enumerate(blocks, 1):
        search = _strip_trailing_whitespace(block.group(1))
        replace = _strip_trailing_whitespace(block.group(2))

        # Empty SEARCH → append at end
        if not search.strip():
            updated_content = updated_content.rstrip("\n") + "\n" + replace + "\n"
            num_applied += 1
            logger.debug("Block %d: Appended to end (empty SEARCH)", i)
            continue

        result = fuzzy_find(updated_content, search)

        if result is not None:
            matched_text = result.matched_text
            pos = updated_content.find(matched_text)
            updated_content = updated_content[:pos] + replace + updated_content[pos + len(matched_text) :]
            num_applied += 1
            logger.debug("Block %d: Applied via fuzzy match at position %d", i, pos)
        else:
            # Not found - provide helpful error
            first_line = search.splitlines()[0].strip() if search.splitlines() else ""
            similar_lines = _find_similar_lines(first_line, updated_content)

            error_parts = [
                f"SEARCH text not found in block {i}/{len(blocks)}",
                "",
                f"Looking for: {first_line!r}",
            ]

            if similar_lines:
                error_parts.append("")
                error_parts.append("Similar lines found:")
                for line, line_num in similar_lines[:3]:  # Top 3 matches
                    error_parts.append(f"  Line {line_num}: {line.strip()}")

            error_parts.extend(
                [
                    "",
                    "Fuzzy match failed at all 7 levels.",
                    "Ensure SEARCH block closely matches file content.",
                ]
            )

            return SkillPatchResult(
                success=False, error_message="\n".join(error_parts), num_changes_applied=num_applied
            )

    return SkillPatchResult(success=True, content=updated_content, num_changes_applied=num_applied)


def _strip_trailing_whitespace(text: str) -> str:
    """Strip trailing whitespace from each line."""
    return "\n".join(line.rstrip() for line in text.splitlines())


def _find_similar_lines(target: str, content: str, max_results: int = 5) -> list[tuple[str, int]]:
    """Find lines in content similar to target.

    Args:
        target: Line to search for
        content: Content to search in
        max_results: Maximum number of results

    Returns:
        List of (line, line_number) tuples sorted by similarity
    """
    if not target:
        return []

    target_lower = target.lower()
    lines = content.splitlines()
    matches = []

    for i, line in enumerate(lines, 1):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Simple similarity: check if target words appear in line
        similarity = sum(1 for word in target_lower.split() if word in line_stripped.lower())

        if similarity > 0:
            matches.append((similarity, line, i))

    # Sort by similarity (descending)
    matches.sort(reverse=True, key=lambda x: x[0])

    return [(line, line_num) for _, line, line_num in matches[:max_results]]


def compute_unified_diff(original: str, updated: str, *, filename: str = SKILL_FILENAME, context: int = 3) -> str:
    """Generate unified diff (git diff format) between two strings.

    Args:
        original: Original content
        updated: Updated content
        filename: Filename for diff headers
        context: Number of context lines

    Returns:
        Unified diff string (empty if no changes)
    """
    diff_lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=context,
    )
    return "".join(diff_lines)
