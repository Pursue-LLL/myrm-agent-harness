"""Configuration for tool-registry validation.

Centralizes scan roots, whitelists, and exemption rules used by
`tool_registry_engine` and `validate_tool_registry` CLI.

Must stay aligned with ``agent/orchestration/signals/catalog.py`` and
``agent/orchestration/hooks.py`` (orchestration signals + runtime hooks).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HARNESS_ROOT = REPO_ROOT / "myrm-agent-harness"
HARNESS_SRC = HARNESS_ROOT / "src" / "myrm_agent_harness"
SERVER_ROOT = REPO_ROOT / "myrm-agent" / "myrm-agent-server"
SERVER_SRC = SERVER_ROOT / "app"

SCAN_ROOTS: tuple[Path, ...] = (HARNESS_SRC, SERVER_SRC)

PTC_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({
    "spawn_subagent",
    "notify",
})

INTERNAL_TOOL_PREFIXES: tuple[str, ...] = ("_",)

# Orchestration signals + runtime hooks — excluded from _TOOL_LAYERS (see agent/orchestration/).
INTERNAL_TOOL_NAMES: frozenset[str] = frozenset({
    "_completion_check",
    "submit_verdict",
})

# JSON schema signals (no @tool AST) — DR orchestrator bind_tools only.
SCHEMA_ONLY_TOOL_NAMES: frozenset[str] = frozenset({
    "dispatch_research",
    "finalize_report",
    "think",
})

CROSS_MODULE_CONSTANTS: dict[str, str] = {
    "CONVERSATION_SEARCH_TOOL_NAME": "conversation_search_tool",
}

ORPHAN_FACTORY_WHITELIST: frozenset[str] = frozenset({
    "create_desktop_tools",
    "create_browser_tools",
    "create_skill_select_tool",
    "create_kanban_tools",
    "create_conversation_search_tool",
    "create_cron_tools",
    "create_delegate_to_agent_tool",
    "create_goal_tools",
    "create_memory_tools",
    "create_submit_verdict_tool",
})

BOOTSTRAP_FILES: frozenset[str] = frozenset({
    "myrm-agent/myrm-agent-server/app/ai_agents/general_agent/tools/_tool_layer_bootstrap.py",
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
