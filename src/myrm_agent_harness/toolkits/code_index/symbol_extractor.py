"""Regex-based code symbol extractor.

[INPUT]
re (POS: standard library regex)
pathlib::Path (POS: standard library path)

[OUTPUT]
CodeSymbol: extracted code symbol dataclass
extract_symbols: extract function/class definitions from source code

[POS]
Lightweight regex-based symbol extraction for code indexing. Extracts
function, class, and method definitions without requiring full AST parsing
or tree-sitter. Supports 15+ languages via configurable pattern sets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CodeSymbol:
    """A single extracted code symbol (function, class, method, etc.)."""

    name: str
    kind: str  # "function" | "class" | "method" | "interface" | "type" | "constant"
    line: int
    signature: str
    file_path: str


_LANG_BY_EXT: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala",
    ".lua": "lua",
    ".r": "r", ".R": "r",
    ".pl": "perl", ".pm": "perl",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".sql": "sql",
    ".ex": "elixir", ".exs": "elixir",
}


_SYMBOL_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "python": [
        ("function", re.compile(r"^(\s*)def\s+(\w+)\s*\(([^)]*)\)(?:\s*->.*)?:", re.MULTILINE)),
        ("class", re.compile(r"^(\s*)class\s+(\w+)(?:\s*\(([^)]*)\))?\s*:", re.MULTILINE)),
    ],
    "javascript": [
        ("function", re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", re.MULTILINE)),
        ("class", re.compile(r"^(?:export\s+)?class\s+(\w+)", re.MULTILINE)),
        ("constant", re.compile(r"^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(", re.MULTILINE)),
    ],
    "typescript": [
        ("function", re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*[<(]", re.MULTILINE)),
        ("class", re.compile(r"^(?:export\s+)?class\s+(\w+)", re.MULTILINE)),
        ("interface", re.compile(r"^(?:export\s+)?interface\s+(\w+)", re.MULTILINE)),
        ("type", re.compile(r"^(?:export\s+)?type\s+(\w+)\s*[<=]", re.MULTILINE)),
        ("constant", re.compile(r"^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(", re.MULTILINE)),
    ],
    "java": [
        ("class", re.compile(r"^\s*(?:public|private|protected)?\s*(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)),
        ("interface", re.compile(r"^\s*(?:public\s+)?interface\s+(\w+)", re.MULTILINE)),
        ("method", re.compile(r"^\s*(?:public|private|protected)\s+(?:static\s+)?(?:\w+(?:<[^>]*>)?)\s+(\w+)\s*\(", re.MULTILINE)),
    ],
    "go": [
        ("function", re.compile(r"^func\s+(\w+)\s*\(", re.MULTILINE)),
        ("method", re.compile(r"^func\s+\([^)]+\)\s+(\w+)\s*\(", re.MULTILINE)),
        ("type", re.compile(r"^type\s+(\w+)\s+(?:struct|interface)", re.MULTILINE)),
    ],
    "rust": [
        ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", re.MULTILINE)),
        ("class", re.compile(r"^\s*(?:pub\s+)?struct\s+(\w+)", re.MULTILINE)),
        ("interface", re.compile(r"^\s*(?:pub\s+)?trait\s+(\w+)", re.MULTILINE)),
        ("type", re.compile(r"^\s*(?:pub\s+)?enum\s+(\w+)", re.MULTILINE)),
    ],
    "ruby": [
        ("function", re.compile(r"^\s*def\s+(\w+)", re.MULTILINE)),
        ("class", re.compile(r"^\s*class\s+(\w+)", re.MULTILINE)),
    ],
    "c": [
        ("function", re.compile(r"^(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*\{", re.MULTILINE)),
        ("class", re.compile(r"^(?:typedef\s+)?struct\s+(\w+)", re.MULTILINE)),
    ],
    "cpp": [
        ("function", re.compile(r"^(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*(?:const\s*)?(?:override\s*)?\{", re.MULTILINE)),
        ("class", re.compile(r"^\s*class\s+(\w+)", re.MULTILINE)),
    ],
    "csharp": [
        ("class", re.compile(r"^\s*(?:public|internal|private)?\s*(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)),
        ("interface", re.compile(r"^\s*(?:public\s+)?interface\s+(\w+)", re.MULTILINE)),
        ("method", re.compile(r"^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?(?:\w+(?:<[^>]*>)?)\s+(\w+)\s*\(", re.MULTILINE)),
    ],
}

for _alias, _lang in [("php", "javascript"), ("kotlin", "java"), ("swift", "java"),
                       ("scala", "java"), ("perl", "ruby"), ("lua", "ruby")]:
    _SYMBOL_PATTERNS.setdefault(_alias, _SYMBOL_PATTERNS.get(_lang, []))


def detect_language(file_path: str | Path) -> str | None:
    """Detect programming language from file extension."""
    ext = Path(file_path).suffix.lower()
    return _LANG_BY_EXT.get(ext)


def extract_symbols(content: str, file_path: str, language: str | None = None) -> list[CodeSymbol]:
    """Extract code symbols from source file content.

    Args:
        content: Source file text content.
        file_path: Relative file path (for metadata).
        language: Language override. Auto-detected from extension if None.

    Returns:
        List of extracted CodeSymbol entries.
    """
    lang = language or detect_language(file_path)
    if not lang or lang not in _SYMBOL_PATTERNS:
        return []

    symbols: list[CodeSymbol] = []
    lines = content.split("\n")
    line_offsets = _build_line_offsets(content)
    patterns = _SYMBOL_PATTERNS[lang]

    for kind, pattern in patterns:
        for match in pattern.finditer(content):
            line_num = _offset_to_line(match.start(), line_offsets)
            name = _extract_name(match, kind, lang)
            if not name or name.startswith("_") and len(name) <= 2:
                continue
            sig_line = lines[line_num - 1].strip() if line_num <= len(lines) else ""
            symbols.append(CodeSymbol(
                name=name,
                kind=kind,
                line=line_num,
                signature=sig_line[:200],
                file_path=file_path,
            ))

    return symbols


def _extract_name(match: re.Match[str], kind: str, lang: str) -> str | None:
    """Extract the symbol name from a regex match based on language and kind."""
    if lang == "python":
        return match.group(2)
    groups = match.groups()
    for g in groups:
        if g and not g.isspace():
            cleaned = g.strip()
            if cleaned and cleaned[0].isalpha():
                return cleaned
    return None


def _build_line_offsets(content: str) -> list[int]:
    """Build a list of byte offsets for each line start."""
    offsets = [0]
    for i, ch in enumerate(content):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def _offset_to_line(offset: int, line_offsets: list[int]) -> int:
    """Convert a character offset to a 1-based line number."""
    lo, hi = 0, len(line_offsets) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if line_offsets[mid] <= offset:
            lo = mid + 1
        else:
            hi = mid - 1
    return lo
