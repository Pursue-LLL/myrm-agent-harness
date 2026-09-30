"""Exact Identifier Anchor Indexing Engine.

[INPUT]
- langchain_core.messages::BaseMessage (POS: Message sequence to extract exact anchors from)
- ExactAnchorFilterConfig: Configurable boundaries and capacity limits

[OUTPUT]
- ExactAnchorTable: Immutable frozen dataclass holding verified machine symbols
- ExactAnchorFilterConfig: Config thresholds for symbol extraction and ReDoS protection
- extract_exact_anchors: Pure functional deterministic symbol extractor

[POS]
Harness framework layer context management. Extracts verbatim machine symbols
(Git commit SHAs, file paths, fatal stack trace spans, code symbols, API routes)
before context compaction. Zero LLM cost, bounded memory budget, and strict
Prompt Cache preservation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

# Regex for common deterministic machine symbols with strict character limits
_FILE_PATH_RE = re.compile(
    r"(?:^|[\s\"'`(])("
    r"(?:(?:[a-zA-Z0-9_.-]+/)+[a-zA-Z0-9_.-]+(?:\.[a-zA-Z0-9_-]+)+)"  # multi/level/path/to/file.ext
    r"|(?:[a-zA-Z0-9_.-]+\.(?:py|ts|tsx|js|jsx|rs|go|java|yaml|yml|json|toml|md|sql|sh|css|html|xml|env|lock))"
    r")"
)

_IDENT_RE = re.compile(
    r"(?:def|class|function|interface|type|const|let|var|struct|enum)\s+([a-zA-Z_][a-zA-Z0-9_]{2,})"
)

_COMMIT_SHA_RE = re.compile(
    r"(?:(?:commit|commit\s*[:=]|sha\s*[:=]|rev\s*[:=])\s*([0-9a-f]{7,40})|\b([0-9a-f]{40})\b)",
    re.IGNORECASE,
)

_API_ENDPOINT_RE = re.compile(r"/api/v\d+/[a-zA-Z0-9_/-]+")

_HIGH_SEVERITY_ERROR_RE = re.compile(
    r"((?:Traceback\s*\(most recent call last\):.*?"
    r"|SyntaxError:.*?"
    r"|TypeError:.*?"
    r"|AttributeError:.*?"
    r"|ModuleNotFoundError:.*?"
    r"|ImportError:.*?"
    r"|AssertionError:.*?"
    r"|panic:.*?"
    r"|FATAL ERROR:.*?"
    r"|exit code:\s*[1-9]\d*).*?)(?:\n|$)",
    re.IGNORECASE,
)

_NOISE_WORDS: frozenset[str] = frozenset(
    {
        "true",
        "false",
        "none",
        "null",
        "self",
        "this",
        "async",
        "await",
        "import",
        "from",
        "return",
        "print",
        "error",
        "test",
        "data",
        "index",
        "utils",
        "types",
        "config",
        "setup",
        "init",
    }
)


@dataclass(frozen=True, slots=True)
class ExactAnchorFilterConfig:
    """Configurable quotas and safety boundaries for anchor extraction."""

    max_commit_shas: int = 5
    max_file_paths: int = 15
    max_error_spans: int = 3
    max_code_symbols: int = 10
    max_api_endpoints: int = 5
    max_line_length: int = 2048
    max_scan_total_chars: int = 60000


@dataclass(frozen=True, slots=True)
class ExactAnchorTable:
    """Immutable verified machine symbol anchor table."""

    commit_shas: tuple[str, ...] = field(default_factory=tuple)
    file_paths: tuple[str, ...] = field(default_factory=tuple)
    error_spans: tuple[str, ...] = field(default_factory=tuple)
    code_symbols: tuple[str, ...] = field(default_factory=tuple)
    api_endpoints: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return (
            not self.commit_shas
            and not self.file_paths
            and not self.error_spans
            and not self.code_symbols
            and not self.api_endpoints
        )

    @property
    def total_count(self) -> int:
        return (
            len(self.commit_shas)
            + len(self.file_paths)
            + len(self.error_spans)
            + len(self.code_symbols)
            + len(self.api_endpoints)
        )

    def format_markdown(self) -> str:
        """Format anchors into a compact, prompt-cache friendly Markdown reference table."""
        if self.is_empty:
            return ""

        lines: list[str] = [
            "### ⚓ Exact Anchor Index (Machine-Extracted Truth)",
            "<!-- Immutable historical anchors; do not hallucinate alternatives -->",
        ]

        if self.commit_shas:
            shas = ", ".join(f"`{sha}`" for sha in self.commit_shas)
            lines.append(f"- **Git Commits**: {shas}")

        if self.file_paths:
            paths = ", ".join(f"`{p}`" for p in self.file_paths)
            lines.append(f"- **Modified Files**: {paths}")

        if self.code_symbols:
            symbols = ", ".join(f"`{s}`" for s in self.code_symbols)
            lines.append(f"- **Key Symbols**: {symbols}")

        if self.api_endpoints:
            endpoints = ", ".join(f"`{ep}`" for ep in self.api_endpoints)
            lines.append(f"- **API Endpoints**: {endpoints}")

        if self.error_spans:
            lines.append("- **Resolved Errors**:")
            for err in self.error_spans:
                clean_err = err.strip().replace("\n", " ")
                if len(clean_err) > 140:
                    clean_err = clean_err[:140] + "..."
                lines.append(f"  * `{clean_err}`")

        # Append compact JSON comment metadata for deterministic parsing across boundaries
        json_meta = json.dumps(self.to_dict(), separators=(",", ":"))
        lines.append(f"<!-- EXACT_ANCHOR_JSON: {json_meta} -->")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "commit_shas": list(self.commit_shas),
            "file_paths": list(self.file_paths),
            "error_spans": list(self.error_spans),
            "code_symbols": list(self.code_symbols),
            "api_endpoints": list(self.api_endpoints),
        }


def extract_exact_anchors(
    messages: Sequence[BaseMessage],
    config: ExactAnchorFilterConfig | None = None,
) -> ExactAnchorTable:
    """Deterministically extract exact machine symbols from messages before compaction.

    Runs in sub-millisecond CPU time with zero LLM cost and strictly bounded memory.
    """
    cfg = config or ExactAnchorFilterConfig()

    shas: list[str] = []
    seen_shas: set[str] = set()

    paths: list[str] = []
    seen_paths: set[str] = set()

    errors: list[str] = []
    seen_errors: set[str] = set()

    symbols: list[str] = []
    seen_symbols: set[str] = set()

    endpoints: list[str] = []
    seen_endpoints: set[str] = set()

    total_scanned_chars = 0

    for msg in messages:
        if total_scanned_chars >= cfg.max_scan_total_chars:
            break

        content = msg.content if isinstance(msg.content, str) else ""
        if not content:
            continue

        for raw_line in content.splitlines():
            total_scanned_chars += len(raw_line)
            if total_scanned_chars >= cfg.max_scan_total_chars:
                break

            # Hard truncation for line length to protect against ReDoS
            line = raw_line[: cfg.max_line_length].strip()
            if not line:
                continue

            # 1. Commit SHAs
            if len(shas) < cfg.max_commit_shas:
                for match in _COMMIT_SHA_RE.finditer(line):
                    sha = match.group(1) or match.group(2)
                    if sha and sha.lower() not in seen_shas:
                        seen_shas.add(sha.lower())
                        shas.append(sha)
                        if len(shas) >= cfg.max_commit_shas:
                            break

            # 2. File Paths
            if len(paths) < cfg.max_file_paths:
                for match in _FILE_PATH_RE.finditer(line):
                    path = match.group(1).strip(" \"'`()")
                    if path and path not in seen_paths and len(path) >= 4:
                        seen_paths.add(path)
                        paths.append(path)
                        if len(paths) >= cfg.max_file_paths:
                            break

            # 3. High severity errors
            if len(errors) < cfg.max_error_spans:
                for match in _HIGH_SEVERITY_ERROR_RE.finditer(line):
                    err = match.group(1).strip()
                    if err and err not in seen_errors:
                        seen_errors.add(err)
                        errors.append(err)
                        if len(errors) >= cfg.max_error_spans:
                            break

            # 4. Code symbols
            if len(symbols) < cfg.max_code_symbols:
                for match in _IDENT_RE.finditer(line):
                    sym = match.group(1).strip()
                    if (
                        sym
                        and sym.lower() not in seen_symbols
                        and sym.lower() not in _NOISE_WORDS
                        and len(sym) >= 3
                    ):
                        seen_symbols.add(sym.lower())
                        symbols.append(sym)
                        if len(symbols) >= cfg.max_code_symbols:
                            break

            # 5. API Endpoints
            if len(endpoints) < cfg.max_api_endpoints:
                for match in _API_ENDPOINT_RE.finditer(line):
                    ep = match.group(0).strip()
                    if ep and ep not in seen_endpoints:
                        seen_endpoints.add(ep)
                        endpoints.append(ep)
                        if len(endpoints) >= cfg.max_api_endpoints:
                            break

    return ExactAnchorTable(
        commit_shas=tuple(shas),
        file_paths=tuple(paths),
        error_spans=tuple(errors),
        code_symbols=tuple(symbols),
        api_endpoints=tuple(endpoints),
    )
