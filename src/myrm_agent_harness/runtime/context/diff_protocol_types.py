"""Unified Diff Models, Error Finding Types, and Parser (Pi Harness v2 Item 25 Part 1).

[INPUT]
- unified diff text blocks with markdown fences or standard git headers

[OUTPUT]
- DiffLineKind
- DiffLine
- DiffHunk
- DiffOperation
- PatchDriftFinding
- DiffProtocolError
- DiffApplyResult
- parse_diff_operations

[POS]
Harness runtime context layer. Data models and parser for model-generated unified diffs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_HEADER_PATTERN = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$", re.MULTILINE)
_HUNK_PATTERN = re.compile(r"^@@.*@@(?:.*)?$", re.MULTILINE)


class DiffLineKind(StrEnum):
    """Classification of lines within a diff hunk."""

    CONTEXT = "context"
    ADD = "add"
    REMOVE = "remove"


@dataclass(slots=True, frozen=True)
class DiffLine:
    """A single line in a diff hunk."""

    kind: DiffLineKind
    text: str


@dataclass(slots=True, frozen=True)
class DiffHunk:
    """A unified diff hunk consisting of context, additions, and removals."""

    lines: tuple[DiffLine, ...]
    header: str = ""

    @property
    def remove_lines(self) -> list[str]:
        return [line.text for line in self.lines if line.kind == DiffLineKind.REMOVE]

    @property
    def add_lines(self) -> list[str]:
        return [line.text for line in self.lines if line.kind == DiffLineKind.ADD]

    @property
    def context_lines(self) -> list[str]:
        return [line.text for line in self.lines if line.kind == DiffLineKind.CONTEXT]


@dataclass(slots=True, frozen=True)
class DiffOperation:
    """A single file diff operation encompassing one or more hunks."""

    path: str
    old_path: str
    new_path: str
    hunks: tuple[DiffHunk, ...]
    source: str

    @property
    def is_creation(self) -> bool:
        return self.old_path in ("/dev/null", "a/dev/null") or self.old_path.endswith("/dev/null")

    @property
    def is_deletion(self) -> bool:
        return self.new_path in ("/dev/null", "b/dev/null") or self.new_path.endswith("/dev/null")


@dataclass(slots=True, frozen=True)
class PatchDriftFinding:
    """Diagnostic detail when a diff cannot be safely and unambiguously applied."""

    hunk_index: int
    target_path: str
    candidate_count: int
    max_score: int
    tied_candidates: int
    message: str


class DiffProtocolError(ValueError):
    """Raised when diff parsing or application violates invariants."""

    def __init__(self, message: str, finding: PatchDriftFinding | None = None) -> None:
        super().__init__(message)
        self.finding = finding


@dataclass(slots=True, frozen=True)
class DiffApplyResult:
    """Result of applying a unified diff operation."""

    target_path: str
    original_content: str
    patched_content: str
    hunks_applied: int
    is_created: bool = False
    is_deleted: bool = False


def _path_from_marker(line: str, prefix: str) -> str | None:
    if not line.startswith(prefix):
        return None
    return line[len(prefix):].strip().split("\t", 1)[0]


def parse_diff_operations(
    text: str,
) -> tuple[list[DiffOperation], list[tuple[int, str, DiffProtocolError]]]:
    """Parse all `diff --git` operations from text with markdown fence bleed guard."""
    headers = list(_HEADER_PATTERN.finditer(text))
    ops: list[DiffOperation] = []
    errors: list[tuple[int, str, DiffProtocolError]] = []

    for index, header in enumerate(headers):
        position = index + 1
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        source = text[header.start():end]
        old_header, new_header = header.group(1), header.group(2)
        old_path, new_path = f"a/{old_header}", f"b/{new_header}"

        marker_lines = source.splitlines()
        for line in marker_lines[1:]:
            old_path = _path_from_marker(line, "--- ") or old_path
            new_path = _path_from_marker(line, "+++ ") or new_path
            if line.startswith("@@"):
                break

        raw_target = new_header
        try:
            target = new_path[2:] if new_path.startswith("b/") else new_path
            if not target or target == "/dev/null":
                if old_header and old_header != "/dev/null":
                    raise DiffProtocolError(
                        f"Deletion diff for '{old_header}' is not supported by this runtime."
                    )
                raise DiffProtocolError("Diff is missing a writable +++ target path.")

            raw_target = target
            is_markdown = target.lower().endswith((".md", ".mdx", ".markdown"))

            hunk_marks = list(_HUNK_PATTERN.finditer(source))
            if not hunk_marks:
                raise DiffProtocolError(f"Diff for '{target}' has no @@ hunk marker.")

            hunks: list[DiffHunk] = []
            for hunk_idx, mark in enumerate(hunk_marks):
                body_end = hunk_marks[hunk_idx + 1].start() if hunk_idx + 1 < len(hunk_marks) else len(source)
                body = source[mark.end():body_end]
                if body.startswith("\n"):
                    body = body[1:]

                lines: list[DiffLine] = []
                for raw in body.splitlines():
                    stripped = raw.strip()
                    if stripped.startswith("```"):
                        break
                    if not is_markdown and raw.startswith("+") and not raw.startswith("++"):
                        inner = raw[1:].strip()
                        if inner.startswith("```"):
                            break
                    if raw.startswith("\\ No newline at end of file"):
                        continue
                    if raw.startswith("+") and not raw.startswith("+++"):
                        lines.append(DiffLine(DiffLineKind.ADD, raw[1:]))
                    elif raw.startswith("-") and not raw.startswith("---"):
                        lines.append(DiffLine(DiffLineKind.REMOVE, raw[1:]))
                    elif raw.startswith(" "):
                        lines.append(DiffLine(DiffLineKind.CONTEXT, raw[1:]))
                    elif raw == "":
                        lines.append(DiffLine(DiffLineKind.CONTEXT, ""))
                    else:
                        raise DiffProtocolError(
                            f"Malformed hunk line in '{target}': {raw!r} (expected space, +, or - prefix)."
                        )
                if not lines:
                    raise DiffProtocolError(f"Empty hunk in diff for '{target}'.")
                hunks.append(DiffHunk(tuple(lines), header=mark.group(0)))

            ops.append(DiffOperation(target, old_path, new_path, tuple(hunks), source))
        except DiffProtocolError as exc:
            errors.append((position, raw_target, exc))

    return ops, errors
