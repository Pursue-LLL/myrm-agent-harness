# [POS]: myrm_agent_harness/toolkits/memory/drift_defense/reference_extractor.py
# [INPUT]: re, types
# [OUTPUT]: GroundTruthReferenceExtractor, ExtractedReference
"""Zero-LLM fast regular expression extractor for file paths and code symbols.

Extracts potential ground-truth targets (file paths, configurations, symbols)
from memory text in sub-millisecond execution.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field


class ExtractedReference(BaseModel):
    """Reference target discovered within memory text."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(..., description="Target path, file name, or symbol identifier")
    kind: str = Field(..., description="Reference kind: 'file_path', 'config_key', or 'symbol'")


class GroundTruthReferenceExtractor:
    """High-performance regex extractor for references without LLM overhead."""

    # Matches relative file paths like 'src/core/auth.py', 'config.json', 'docs/api.md'
    _PATH_REGEX = re.compile(
        r"(?:(?:[\w\.\-]+/)+[\w\.\-]+\.[a-zA-Z0-9]+|(?:[a-zA-Z0-9_\-]+\.(?:py|json|yaml|yml|toml|md|ts|js|rs|go|sh|sql)))"
    )

    # Matches code symbols like 'class UserProfile', 'def handle_request', 'function def handle_request'
    _SYMBOL_REGEX = re.compile(
        r"\b(?:class|def|fn|function|struct|interface|async)(?:\s+(?:class|def|fn|function|struct|interface|async))*\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    )

    # Matches environment / configuration keys like 'DATABASE_URL', 'AUTH_SECRET_KEY'
    _CONFIG_KEY_REGEX = re.compile(
        r"\b([A-Z][A-Z0-9_]{3,31})\b"
    )

    def extract(self, text: str) -> list[ExtractedReference]:
        """Extract all candidate reference targets from textual content."""
        results: list[ExtractedReference] = []
        seen: set[str] = set()
        keyword_blacklist = {"class", "def", "fn", "function", "struct", "interface", "async"}

        # 1. Extract file paths
        for match in self._PATH_REGEX.finditer(text):
            path_str = match.group(0).strip("`'\"()[],.")
            if path_str and path_str not in seen:
                seen.add(path_str)
                results.append(ExtractedReference(target=path_str, kind="file_path"))

        # 2. Extract function / class symbols
        for match in self._SYMBOL_REGEX.finditer(text):
            sym = match.group(1).strip()
            if sym and sym not in seen and sym.lower() not in keyword_blacklist:
                seen.add(sym)
                results.append(ExtractedReference(target=sym, kind="symbol"))

        # 3. Extract uppercase config keys (filtering out common words)
        ignore_config = {"HTTP", "JSON", "YAML", "REST", "TRUE", "FALSE", "NULL", "NONE", "UUID", "INFO", "WARN"}
        for match in self._CONFIG_KEY_REGEX.finditer(text):
            cfg = match.group(1).strip()
            if cfg and cfg not in seen and cfg not in ignore_config:
                seen.add(cfg)
                results.append(ExtractedReference(target=cfg, kind="config_key"))

        return results
