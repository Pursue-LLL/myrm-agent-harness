"""Grep result formatter.

[OUTPUT]
- compact_match_line: Truncates long match lines preserving match context
- format_grep_results: Formats search results into LLM-friendly output

[POS]
Grep output formatter. Transforms raw search matches into LLM-friendly output
with intelligent truncation, non-code file capping, and path-grouped
densification (eliminates repeated path strings when >= 5 matches span 2+ files,
saving 18-30% tokens in typical scenarios).
"""

from __future__ import annotations

from pathlib import PurePosixPath

MAX_LINE_CHARS = 240
LINE_PREFIX_CONTEXT_CHARS = 80
NON_CODE_MATCH_CAP = 3
_DENSIFY_MIN_MATCHES = 5
_DENSIFY_MIN_FILES = 2
_NON_CODE_EXTENSIONS = frozenset(
    {
        ".json",
        ".yaml",
        ".yml",
        ".md",
        ".txt",
        ".csv",
        ".toml",
        ".ini",
        ".cfg",
        ".xml",
        ".html",
        ".lock",
        ".log",
        ".svg",
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
    """Format grep results with non-code truncation and path-grouped densification.

    When total matches >= _DENSIFY_MIN_MATCHES across >= _DENSIFY_MIN_FILES,
    groups consecutive matches under a single path header to eliminate repeated
    path strings (saves 18-30% tokens). Falls back to flat ``path:line: content``
    format for small result sets where densification adds no benefit.
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

    total_matches = sum(1 for r in results if r.get("type", "match") == "match")
    densify = (
        total_matches >= _DENSIFY_MIN_MATCHES
        and len(files_order) >= _DENSIFY_MIN_FILES
    )

    lines: list[str] = [f"Found {total_matches} match(es) for '{pattern}' (searched {files_searched} file(s)):\n"]

    for fp in files_order:
        file_matches = matches_by_file[fp]

        is_non_code = _is_non_code_file(fp)
        visible_matches: list[dict[str, str | int]] = []
        match_count = 0

        for m in file_matches:
            if m.get("type", "match") == "match":
                match_count += 1
            if is_non_code and match_count > NON_CODE_MATCH_CAP:
                break
            visible_matches.append(m)

        total_file_matches = sum(1 for m in file_matches if m.get("type", "match") == "match")
        omitted_count = total_file_matches - match_count if is_non_code else 0

        if densify:
            lines.append(fp)

        last_line_num = -2
        for m in visible_matches:
            line_num = int(m["line"])
            content = compact_match_line(str(m["content"]), pattern, is_regex)
            line_type = m.get("type", "match")

            if last_line_num != -2 and line_num > last_line_num + 1:
                lines.append("  --" if densify else "--")
            last_line_num = line_num

            sep = ":" if line_type == "match" else "-"
            if densify:
                lines.append(f"  {line_num}{sep} {content}")
            else:
                lines.append(f"{fp}{sep}{line_num}{sep} {content}")

        if omitted_count > 0:
            lines.append(f"  ... {omitted_count} more non-code matches omitted in {fp}")

    if total_matches >= max_results:
        lines.append(f"\n... (limited to first {max_results} results)")

    return "\n".join(lines)
