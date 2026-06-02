"""Configuration for tool-registry validation.

Centralizes scan roots, whitelists, and exemption rules used by
`tool_registry_engine` and `validate_tool_registry` CLI.

Design principle: Explicit allow-list over implicit guesswork. Every tool
exemption MUST carry a justification in this module so reviewers can audit
the boundary without spelunking the codebase.
"""

from __future__ import annotations

import os
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
HARNESS_ROOT = Path(os.environ.get("MYRM_HARNESS_ROOT", _SCRIPTS_DIR.parent)).resolve()
HARNESS_SRC = HARNESS_ROOT / "src" / "myrm_agent_harness"


def _resolve_server_root() -> Path:
    if env_root := os.environ.get("MYRM_SERVER_ROOT"):
        return Path(env_root).resolve()
    candidates = (
        HARNESS_ROOT / "vortexai" / "myrm-agent-server",
        HARNESS_ROOT.parent / "open-perplexity" / "myrm-agent-server",
        HARNESS_ROOT.parent / "vortexai" / "myrm-agent-server",
        HARNESS_ROOT.parent / "myrm-agent-server",
    )
    for candidate in candidates:
        if (candidate / "app").is_dir():
            return candidate.resolve()
    msg = (
        "Could not locate myrm-agent-server checkout. "
        "Set MYRM_SERVER_ROOT or checkout vortexai beside the harness repo."
    )
    raise FileNotFoundError(msg)


SERVER_ROOT = _resolve_server_root()
SERVER_SRC = SERVER_ROOT / "app"
REPO_ROOT = HARNESS_ROOT

SCAN_ROOTS: tuple[Path, ...] = (HARNESS_SRC, SERVER_SRC)

INTERNAL_TOOL_PREFIXES: tuple[str, ...] = ("_",)

INTERNAL_TOOL_NAMES: frozenset[str] = frozenset({
    "_completion_check",
    "submit_verdict",
})

SCHEMA_ONLY_TOOL_NAMES: frozenset[str] = frozenset({
    "dispatch_research",
    "finalize_report",
    "think",
})

CROSS_MODULE_CONSTANTS: dict[str, str] = {
    "CONVERSATION_SEARCH_TOOL_NAME": "conversation_search_tool",
    "TOOL_NAME": "skill_analyze_tool",
}

ORPHAN_FACTORY_WHITELIST: frozenset[str] = frozenset({
    "create_desktop_tools",
    "create_browser_tools",
    "create_skill_select_tool",
    "create_huggingface_inference_tool",
    "create_automation_tools",
    "create_calendar_tools",
    "create_kanban_tools",
})

BOOTSTRAP_FILE_PATHS: frozenset[Path] = frozenset({
    SERVER_ROOT / "app/ai_agents/general_agent/tools/_tool_layer_bootstrap.py",
})

EXCLUDED_DIRS: frozenset[str] = frozenset({
    "__pycache__",
    "tests",
    "node_modules",
    ".venv",
    "venv",
    "build",
    "dist",
})


def is_test_path(path: Path) -> bool:
    """Heuristic: a file is test code if any path segment looks test-related."""
    parts = {p.lower() for p in path.parts}
    return bool(parts & {"tests", "test", "testing", "conftest.py", "fixtures"})


def validate_config() -> None:
    """Validate config at import time. Raises AssertionError on misuse."""
    assert SCAN_ROOTS, "SCAN_ROOTS must not be empty"
    for root in SCAN_ROOTS:
        assert root.is_absolute(), f"SCAN_ROOTS entries must be absolute: {root}"
    for name in INTERNAL_TOOL_NAMES:
        assert name and isinstance(name, str), f"Invalid internal tool name: {name!r}"
    for factory in ORPHAN_FACTORY_WHITELIST:
        assert factory.startswith("create_"), (
            f"ORPHAN_FACTORY_WHITELIST entries must start with 'create_': {factory}"
        )


validate_config()
