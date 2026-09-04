"""Adaptive structural outline extractor for files.

Extracts top-level class, function, interface, struct signatures, and Markdown headings
from source code or document files. Supports truncated file reads and structure-only reading mode.

[INPUT]
- output: Raw or gutter-formatted file content string
- path_str: Target file path
- next_offset: 1-indexed line number where extraction starts (1 for full document)

[OUTPUT]
- extract_file_outline: Formatted document structure outline string, or empty string
- extract_truncated_outline: Formatted outline string block for truncated reads, or empty string

[POS]
In-memory zero-dependency outline extraction supporting Python (AST + regex fallback),
TypeScript/JavaScript, Go, Rust, Java, C/C++, C#, and Markdown.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass

# Matches line gutter emitted by ResultFormatter (e.g. "     12|def foo():")
_GUTTER_LINE_RE = re.compile(r"^\s*(\d+)\|")

# Pre-compiled symbol matching regexes for non-Python or fallback extraction
# Each pattern captures (kind, name) or (name)
_GENERIC_SYMBOL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "ts_js": [
        re.compile(r"^(?:export\s+(?:default\s+)?)?((?:async\s+)?function)\s+([a-zA-Z0-9_$]+)\s*\("),
        re.compile(r"^(?:export\s+(?:default\s+)?)?(class)\s+([a-zA-Z0-9_$]+)"),
        re.compile(r"^(?:export\s+)?(interface)\s+([a-zA-Z0-9_$]+)"),
        re.compile(r"^(?:export\s+)?(type)\s+([a-zA-Z0-9_$]+)\s*="),
        re.compile(r"^(?:export\s+)?(enum)\s+([a-zA-Z0-9_$]+)"),
        re.compile(r"^(?:export\s+)?(const)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"),
    ],
    "go": [
        re.compile(r"^(func)\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)\s*\("),
        re.compile(r"^(type)\s+([a-zA-Z0-9_]+)\s+(?:struct|interface)"),
    ],
    "rust": [
        re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?((?:async\s+)?fn)\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?(struct|enum|trait|type)\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^(impl)(?:\s*<[^>]+>)?\s+([a-zA-Z0-9_]+)"),
    ],
    "java_csharp": [
        re.compile(r"^(?:public|protected|private|static|final|abstract|sealed|\s)*(class)\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^(?:public|protected|private|static|final|abstract|\s)*(interface)\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^(?:public|protected|private|static|final|abstract|\s)*(enum)\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^(?:public|protected|private|static|async|\s)+[\w<>\[\],\s]+\s+([a-zA-Z0-9_]+)\s*\([^;]*$"),
    ],
    "c_cpp": [
        re.compile(r"^(class|struct|enum)\s+([a-zA-Z0-9_]+)"),
        re.compile(r"^(?:[\w:*&<>\s]+)\s+([a-zA-Z0-9_]+)\s*\([^;]*\)\s*(?:const)?\s*\{?"),
    ],
    "python_fallback": [
        re.compile(r"^((?:async\s+)?def)\s+([a-zA-Z0-9_]+)\s*\("),
        re.compile(r"^(class)\s+([a-zA-Z0-9_]+)"),
    ],
    "markdown": [
        re.compile(r"^(#{1,6})\s+(.+)$"),
    ],
}

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "ts_js",
    ".tsx": "ts_js",
    ".js": "ts_js",
    ".jsx": "ts_js",
    ".mjs": "ts_js",
    ".cjs": "ts_js",
    ".go": "go",
    ".rs": "rust",
    ".java": "java_csharp",
    ".cs": "java_csharp",
    ".cpp": "c_cpp",
    ".cc": "c_cpp",
    ".cxx": "c_cpp",
    ".hpp": "c_cpp",
    ".h": "c_cpp",
    ".c": "c_cpp",
    ".md": "markdown",
    ".mdx": "markdown",
}


@dataclass(frozen=True, slots=True)
class OutlineSymbol:
    """Represents an extracted code symbol with line boundaries."""

    name: str
    kind: str
    start_line: int
    end_line: int | None = None

    def format_entry(self) -> str:
        """Format symbol entry with single line or line range."""
        if self.end_line and self.end_line > self.start_line:
            return f"- Line {self.start_line}-{self.end_line}: {self.kind} {self.name}"
        return f"- Line {self.start_line}: {self.kind} {self.name}"


def _strip_gutter_line(line: str) -> tuple[int | None, str]:
    """Strip line number gutter if present and return (line_number, raw_text)."""
    match = _GUTTER_LINE_RE.match(line)
    if match:
        line_num = int(match.group(1))
        raw_text = line[match.end():]
        return line_num, raw_text
    return None, line


def _clean_path_extension(path_str: str) -> str:
    """Extract clean file extension from path string which may include line ranges or URI schemes."""
    clean_path = path_str.split(":")[0] if ":" in path_str else path_str
    clean_path = clean_path.split("?")[0]
    return os.path.splitext(clean_path)[1].lower()


def _extract_python_ast_symbols(raw_content: str, start_line_threshold: int) -> list[OutlineSymbol]:
    """Extract top-level and class-level Python symbols using AST."""
    try:
        tree = ast.parse(raw_content)
    except SyntaxError:
        return []

    symbols: list[OutlineSymbol] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.lineno >= start_line_threshold:
                end_lineno = getattr(node, "end_lineno", None)
                symbols.append(
                    OutlineSymbol(
                        name=node.name,
                        kind="class",
                        start_line=node.lineno,
                        end_line=end_lineno,
                    )
                )
            for subnode in node.body:
                if (
                    isinstance(subnode, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and subnode.lineno >= start_line_threshold
                ):
                    kind = "async def" if isinstance(subnode, ast.AsyncFunctionDef) else "def"
                    end_lineno = getattr(subnode, "end_lineno", None)
                    symbols.append(
                        OutlineSymbol(
                            name=f"{node.name}.{subnode.name}",
                            kind=kind,
                            start_line=subnode.lineno,
                            end_line=end_lineno,
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno >= start_line_threshold:
                kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                end_lineno = getattr(node, "end_lineno", None)
                symbols.append(
                    OutlineSymbol(
                        name=node.name,
                        kind=kind,
                        start_line=node.lineno,
                        end_line=end_lineno,
                    )
                )

    return symbols


def _extract_regex_symbols(
    lines: list[str],
    language_key: str,
    start_line_threshold: int,
) -> list[OutlineSymbol]:
    """Extract code symbols using pre-compiled regex patterns."""
    patterns = _GENERIC_SYMBOL_PATTERNS.get(language_key, [])
    if not patterns:
        return []

    symbols: list[OutlineSymbol] = []
    in_code_block = False

    for idx, line in enumerate(lines, start=1):
        gutter_line, raw_text = _strip_gutter_line(line)
        line_num = gutter_line if gutter_line is not None else idx

        if line_num < start_line_threshold:
            continue

        stripped_code = raw_text.strip()
        if not stripped_code:
            continue
        if language_key == "markdown":
            if stripped_code.startswith(("```", "~~~")):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
        elif stripped_code.startswith(("//", "/*", "*", "#", "'''", '"""')):
            continue
        for pattern in patterns:
            match = pattern.match(stripped_code)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    kind_name, symbol_name = groups[0], groups[1]
                else:
                    kind_name, symbol_name = "def", groups[0]
                symbols.append(
                    OutlineSymbol(
                        name=symbol_name,
                        kind=kind_name,
                        start_line=line_num,
                    )
                )
                break

    return symbols


def extract_truncated_outline(
    output: str,
    path_str: str,
    next_offset: int,
    max_symbols: int = 20,
) -> str:
    """Extract structural outline for omitted lines in a truncated source code file.

    Args:
        output: Full raw or gutter-formatted text before truncation.
        path_str: Path to determine language syntax.
        next_offset: 1-indexed line number of first truncated line.
        max_symbols: Maximum outline items before applying truncation fuse.

    Returns:
        Formatted outline text block or empty string if no relevant symbols found.
    """
    ext = _clean_path_extension(path_str)
    language = _EXT_TO_LANGUAGE.get(ext)
    if not language:
        return ""

    symbols: list[OutlineSymbol] = []
    lines = output.split("\n")

    if language == "python":
        raw_lines = [_strip_gutter_line(line)[1] for line in lines]
        raw_content = "\n".join(raw_lines)
        symbols = _extract_python_ast_symbols(raw_content, start_line_threshold=next_offset)
        if not symbols:
            symbols = _extract_regex_symbols(lines, "python_fallback", start_line_threshold=next_offset)
    else:
        symbols = _extract_regex_symbols(lines, language, start_line_threshold=next_offset)

    if not symbols:
        return ""

    total_symbols = len(symbols)
    displayed_symbols = symbols[:max_symbols]

    outline_lines: list[str] = [
        f"[OUTLINE OF REMAINING SYMBOLS (from line {next_offset})]:"
    ]
    for sym in displayed_symbols:
        outline_lines.append(f"  {sym.format_entry()}")

    if total_symbols > max_symbols:
        omitted = total_symbols - max_symbols
        outline_lines.append(f"  ... and {omitted:,} more symbols.")

    return "\n".join(outline_lines)


def extract_file_outline(
    output: str,
    path_str: str,
    max_symbols: int = 100,
) -> str:
    """Extract structural outline with line numbers for a complete source or markdown file.

    Args:
        output: Full raw or gutter-formatted file text.
        path_str: Path to determine language syntax.
        max_symbols: Maximum outline items before applying truncation fuse.

    Returns:
        Formatted outline text block or empty string.
    """
    ext = _clean_path_extension(path_str)
    language = _EXT_TO_LANGUAGE.get(ext)
    if not language:
        return ""

    lines = output.split("\n")
    if language == "python":
        raw_lines = [_strip_gutter_line(line)[1] for line in lines]
        raw_content = "\n".join(raw_lines)
        symbols = _extract_python_ast_symbols(raw_content, start_line_threshold=1)
        if not symbols:
            symbols = _extract_regex_symbols(lines, "python_fallback", start_line_threshold=1)
    else:
        symbols = _extract_regex_symbols(lines, language, start_line_threshold=1)

    if not symbols:
        return ""

    total_symbols = len(symbols)
    displayed_symbols = symbols[:max_symbols]

    outline_lines: list[str] = [
        f"[DOCUMENT STRUCTURE OUTLINE: {os.path.basename(path_str)}]:"
    ]
    for sym in displayed_symbols:
        outline_lines.append(f"  {sym.format_entry()}")

    if total_symbols > max_symbols:
        omitted = total_symbols - max_symbols
        outline_lines.append(f"  ... and {omitted:,} more symbols.")

    return "\n".join(outline_lines)
