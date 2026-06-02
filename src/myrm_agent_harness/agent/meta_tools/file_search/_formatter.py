"""Grep result formatter.

[OUTPUT]
- compact_match_line: Truncates long match lines preserving match context
- format_grep_results: Formats search results into LLM-friendly output

[POS]
Grep output formatter. Transforms raw search matches into LLM-friendly output
with intelligent truncation and non-code file capping.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from .ast_parser import HAS_TREE_SITTER, ASTParser

MAX_LINE_CHARS = 240
LINE_PREFIX_CONTEXT_CHARS = 80
NON_CODE_MATCH_CAP = 3
_NON_CODE_EXTENSIONS = frozenset(
    {
        ".json", ".yaml", ".yml", ".md", ".txt", ".csv", ".toml", ".ini", ".cfg",
        ".xml", ".html", ".lock", ".log", ".svg",
    }
)


def compact_match_line(line: str, pattern: str, is_regex: bool) -> str:
    """Truncate long match lines, centering on the match point with surrounding context.

    If line length <= MAX_LINE_CHARS, returns unchanged.
    Otherwise, extracts a MAX_LINE_CHARS window around the first match occurrence
    and marks truncated regions.
    """
    char_count = len(line)
    if char_count <= MAX_LINE_CHARS:
        return line

    match_start = 0
    if not is_regex and pattern:
        idx = line.find(pattern)
        if idx >= 0:
            match_start = idx

    start = max(0, match_start - LINE_PREFIX_CONTEXT_CHARS)
    end = min(char_count, start + MAX_LINE_CHARS)
    start = max(0, end - MAX_LINE_CHARS)

    snippet = line[start:end]
    omitted_before = start
    omitted_after = char_count - end

    if omitted_before > 0 and omitted_after > 0:
        return f"\u2026{snippet} \u2026 [truncated: {omitted_before} before, {omitted_after} after]"
    if omitted_before > 0:
        return f"\u2026{snippet} [truncated: {omitted_before} before]"
    if omitted_after > 0:
        return f"{snippet} \u2026 [truncated: {omitted_after} after]"
    return snippet


def _is_non_code_file(file_path: str) -> bool:
    suffix = PurePosixPath(file_path).suffix.lower()
    return suffix in _NON_CODE_EXTENSIONS


def format_grep_results(
    results: list[dict[str, str | int]],
    pattern: str,
    files_searched: int,
    max_results: int,
    is_regex: bool = True,
) -> str:
    """Format grep results as flat file listing with non-code truncation.

    Non-code files (JSON/YAML/etc) are capped to NON_CODE_MATCH_CAP matches
    per file to prevent token flooding.
    """
    if not results:
        return f"No matches found for: {pattern}\n(Searched {files_searched} file(s))"

    files_order: list[str] = []
    matches_by_file: dict[str, list[dict[str, str | int]]] = {}
    for r in results:
        fp = str(r["file"])
        if fp not in matches_by_file:
            files_order.append(fp)
            matches_by_file[fp] = []
        matches_by_file[fp].append(r)

    lines: list[str] = [f"Found {len(results)} match(es) for '{pattern}' (searched {files_searched} file(s)):\n"]

    # Group matches by their AST context
    current_context: str | None = None
    ast_parser = ASTParser() if HAS_TREE_SITTER else None

    for fp in files_order:
        file_matches = matches_by_file[fp]

        is_non_code = _is_non_code_file(fp)
        if is_non_code and len(file_matches) > NON_CODE_MATCH_CAP:
            visible_matches = file_matches[:NON_CODE_MATCH_CAP]
            omitted_count = len(file_matches) - NON_CODE_MATCH_CAP
        else:
            visible_matches = file_matches
            omitted_count = 0

        # Always print the file name first for code files
        if not is_non_code and visible_matches:
            lines.append(f"{fp}")

        for m in visible_matches:
            line_num = int(m["line"])
            content = compact_match_line(str(m["content"]), pattern, is_regex)

            if not is_non_code:
                ctx = ast_parser.get_context_for_line(Path(fp), line_num) if ast_parser else None
                if ctx != current_context:
                    if ctx:
                        lines.append(f"  [{ctx}]")
                    current_context = ctx
                lines.append(f"    {line_num}: {content}")
            else:
                lines.append(f"{fp}:{line_num}: {content}")

        if omitted_count > 0:
            lines.append(f"  ... {omitted_count} more non-code matches omitted")

    if len(results) >= max_results:
        lines.append(f"\n... (limited to first {max_results} results)")

    return "\n".join(lines)
