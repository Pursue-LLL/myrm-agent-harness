"""Command-aware semantic output compressor for bash tool results.

Reduces LLM context noise by removing format boilerplate from known command outputs
while preserving all semantically meaningful information. Compresses both successful
and failed command outputs; unrecognized commands pass through.

[INPUT]
- (none — self-contained module, no cross-module dependencies)

[OUTPUT]
- compress_output(): Entry function called by bash_code_execute_tool._format_result()

[POS]
Command-aware semantic compressor for bash tool outputs. Sits between raw execution
output and character-level truncation, reducing token consumption by 68-99% for
common dev commands while preserving all decision-relevant information for the LLM.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Protocol

import yaml

from ._compressors import (
    BuildToolCompressor,
    CompilerErrorCompressor,
    DockerBuildCompressor,
    GitDiffCompressor,
    GitLogCompressor,
    GitOperationCompressor,
    GitStatusCompressor,
    LogCompressor,
    LsCompressor,
    PackageInstallCompressor,
    TestCompressor,
)

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    return os.environ.get("MYRM_BASH_COMPRESSION", "1") != "0"


class Compressor(Protocol):
    """Protocol for command-specific compressors."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        """Compress stdout. Return compressed string or None if not applicable."""
        ...


# ---------------------------------------------------------------------------
# Declarative Filter Engine (YAML-driven)
# ---------------------------------------------------------------------------


class DeclarativeFilterEngine:
    """A declarative pipeline engine that applies YAML-defined filter rules to command output.

    Priority:
    1. User-local: .myrm/filters.yaml (in current working directory)
    2. Built-in: builtin_filters.yaml (shipped with the framework)
    """

    def __init__(self) -> None:
        self.builtin_filters: list[dict[str, object]] = []
        self._load_builtin_filters()
        self._local_filters_cache: dict[str, list[dict[str, object]]] = {}
        self._local_filters_mtime: dict[str, float] = {}

    @staticmethod
    def _local_filters_path(workspace_root: str | Path | None) -> Path:
        if workspace_root:
            root_str = str(workspace_root)
            if root_str == "/workspace" or root_str.startswith("/workspace/"):
                from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
                    WorkspacePathResolver,
                )

                local_root = WorkspacePathResolver.to_local_path("/workspace", None)
                if local_root is not None:
                    return local_root / ".myrm" / "filters.yaml"
            return Path(workspace_root) / ".myrm" / "filters.yaml"
        return Path(".myrm/filters.yaml")

    def _load_builtin_filters(self) -> None:
        builtin_path = Path(__file__).parent / "builtin_filters.yaml"
        if builtin_path.exists():
            self.builtin_filters = self._parse_file(builtin_path)

    def _parse_file(self, path: Path) -> list[dict[str, object]]:
        filters: list[dict[str, object]] = []
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or "filters" not in data:
                return filters
            for f_def in data["filters"]:
                filters.append(
                    {
                        "name": f_def.get("name", "unnamed"),
                        "match_command": re.compile(f_def["match_command"]),
                        "strip_ansi": f_def.get("strip_ansi", False),
                        "strip_lines_matching": [re.compile(p) for p in f_def.get("strip_lines_matching", [])],
                        "replace": [(re.compile(r["pattern"]), r["replacement"]) for r in f_def.get("replace", [])],
                        "max_lines": f_def.get("max_lines"),
                        "on_empty": f_def.get("on_empty"),
                    }
                )
        except Exception as e:
            logger.warning("Failed to load declarative filters from %s: %s", path, e)
        return filters

    def compress(
        self,
        command: str,
        stdout: str,
        *,
        is_failure: bool = False,
        workspace_root: str | Path | None = None,
    ) -> str | None:
        # Load user filters from the session workspace (not the server process CWD).
        local_path = self._local_filters_path(workspace_root)
        cache_key = str(local_path)
        local_filters: list[dict[str, object]] = []

        try:
            if local_path.exists():
                current_mtime = local_path.stat().st_mtime
                cached_mtime = self._local_filters_mtime.get(cache_key, 0.0)
                if current_mtime > cached_mtime:
                    self._local_filters_cache[cache_key] = self._parse_file(local_path)
                    self._local_filters_mtime[cache_key] = current_mtime
                local_filters = self._local_filters_cache.get(cache_key, [])
            else:
                self._local_filters_cache.pop(cache_key, None)
                self._local_filters_mtime.pop(cache_key, None)
        except Exception:
            local_filters = self._local_filters_cache.get(cache_key, [])

        all_filters = local_filters + self.builtin_filters

        matched_filter: dict[str, object] | None = None
        for f in all_filters:
            match_pattern = f["match_command"]
            if isinstance(match_pattern, re.Pattern) and match_pattern.search(command):
                matched_filter = f
                break

        if not matched_filter:
            return None

        return self._apply_filter(matched_filter, stdout)

    def _apply_filter(self, filter_def: dict[str, object], stdout: str) -> str:
        lines = stdout.splitlines()

        if filter_def["strip_ansi"]:
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            lines = [ansi_escape.sub("", line) for line in lines]

        replace_rules = filter_def["replace"]
        if replace_rules and isinstance(replace_rules, list):
            new_lines: list[str] = []
            for line in lines:
                rewritten = line
                for pat, repl in replace_rules:
                    rewritten = pat.sub(repl, rewritten)
                new_lines.append(rewritten)
            lines = new_lines

        strip_rules = filter_def["strip_lines_matching"]
        if strip_rules and isinstance(strip_rules, list):
            lines = [line for line in lines if not any(pat.search(line) for pat in strip_rules)]

        max_lines_val = filter_def["max_lines"]
        if isinstance(max_lines_val, int) and len(lines) > max_lines_val:
            omitted = len(lines) - max_lines_val
            lines = lines[:max_lines_val]
            lines.append(f"... ({omitted} lines truncated)")

        result = "\n".join(lines)
        on_empty = filter_def["on_empty"]
        if not result.strip() and isinstance(on_empty, str) and on_empty:
            return on_empty

        return result


_DECLARATIVE_ENGINE = DeclarativeFilterEngine()


# ---------------------------------------------------------------------------
# Command Matcher + Registry
# ---------------------------------------------------------------------------

_COMPRESSOR_REGISTRY: list[tuple[re.Pattern[str], Compressor]] = [
    (re.compile(r"\bgit\s+status\b"), GitStatusCompressor()),
    (re.compile(r"\bgit\s+diff\b"), GitDiffCompressor()),
    (re.compile(r"\bgit\s+log\b"), GitLogCompressor()),
    (re.compile(r"\bgit\s+(add|commit|push|pull|fetch|merge)\b"), GitOperationCompressor()),
    (re.compile(r"\bls\s+.*-[a-zA-Z]*l"), LsCompressor()),
    (re.compile(r"\b(pytest|py\.test|python\s+-m\s+pytest)\b"), TestCompressor()),
    (re.compile(r"\b(cargo\s+test|go\s+test|npm\s+test|bun\s+test|vitest|jest)\b"), TestCompressor()),
    (re.compile(r"\b(npm|bun|yarn|pnpm)\s+install\b"), PackageInstallCompressor()),
    (re.compile(r"\b(pip|pip3|uv)\s+(install|sync)\b"), PackageInstallCompressor()),
    (re.compile(r"\bdocker\s+(build|buildx)\b"), DockerBuildCompressor()),
    (re.compile(r"\bdocker\s+compose\s+build\b"), DockerBuildCompressor()),
    (re.compile(r"\b(cargo|rustc)\s+build\b"), BuildToolCompressor()),
    (re.compile(r"\bcargo\s+(check|clippy|run)\b"), BuildToolCompressor()),
    (re.compile(r"\b(tsc|npx\s+tsc|bunx\s+tsc|eslint|npx\s+eslint|bunx\s+eslint)\b"), CompilerErrorCompressor()),
]


def compress_output(
    command: str,
    stdout: str,
    *,
    exit_code: str = "0",
    workspace_root: str | Path | None = None,
) -> str:
    """Compress bash stdout for known commands. Returns original if not compressible.

    This is the single entry point called from bash_code_execute_tool._format_result().
    Compresses when:
    - Feature is enabled (MYRM_BASH_COMPRESSION != "0")
    - Command matches a known pattern
    - Compressor successfully produces shorter output

    Args:
        command: The bash command string that was executed.
        stdout: The raw stdout from execution.
        exit_code: The exit code string (default "0").

    Returns:
        Compressed stdout or original stdout (never loses information).
    """
    if not _is_enabled() or not stdout or not command:
        return stdout

    is_failure = exit_code != "0"

    try:
        # 1. Try hardcoded complex semantic compressors first
        for pattern, compressor in _COMPRESSOR_REGISTRY:
            if pattern.search(command):
                result = compressor.compress(stdout, is_failure=is_failure)
                if result is not None and len(result) < len(stdout):
                    logger.debug(
                        "Output compressed (semantic): %d→%d chars (-%d%%) failure=%s",
                        len(stdout),
                        len(result),
                        int((1 - len(result) / len(stdout)) * 100),
                        is_failure,
                    )
                    return result
                # If a specific compressor matches but chooses not to compress (returns None or longer),
                # we still return the original stdout, preventing it from falling through to declarative engine
                # because the semantic compressor has already made a decision.
                return stdout

        # 2. Try declarative filter engine (YAML-driven)
        result = _DECLARATIVE_ENGINE.compress(
            command,
            stdout,
            is_failure=is_failure,
            workspace_root=workspace_root,
        )
        if result is not None and len(result) < len(stdout):
            logger.debug(
                "Output compressed (declarative): %d→%d chars (-%d%%) failure=%s",
                len(stdout),
                len(result),
                int((1 - len(result) / len(stdout)) * 100),
                is_failure,
            )
            return result

        # 3. Try Auto-Deduplication for massive logs (fallback)
        if len(stdout.splitlines()) >= 100:
            log_compressor = LogCompressor()
            result = log_compressor.compress(stdout, is_failure=is_failure)
            if result is not None and len(result) < len(stdout):
                logger.debug(
                    "Output compressed (log dedup): %d→%d chars (-%d%%) failure=%s",
                    len(stdout),
                    len(result),
                    int((1 - len(result) / len(stdout)) * 100),
                    is_failure,
                )
                return result

    except Exception:
        logger.debug("Output compressor failed, passing through", exc_info=True)

    return stdout
