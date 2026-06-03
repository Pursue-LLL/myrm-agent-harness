"""Configuration for tool-registry validation.

Centralizes scan roots, whitelists, and exemption rules used by
`tool_registry_engine` and `validate_tool_registry` CLI.

Design principle: Explicit allow-list over implicit guesswork. Every tool
exemption MUST carry a justification in this module so reviewers can audit
the boundary without spelunking the codebase.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HARNESS_ROOT = REPO_ROOT / "myrm-agent-harness"
HARNESS_SRC = HARNESS_ROOT / "src" / "myrm_agent_harness"
SERVER_ROOT = REPO_ROOT / "myrm-agent-server"
SERVER_SRC = SERVER_ROOT / "app"

SCAN_ROOTS: tuple[Path, ...] = (HARNESS_SRC, SERVER_SRC)

INTERNAL_TOOL_PREFIXES: tuple[str, ...] = ("_",)

INTERNAL_TOOL_NAMES: frozenset[str] = frozenset({
    "_completion_check",
    "submit_verdict",
})

# Tools registered in _TOOL_LAYERS but injected as raw JSON schemas (not via
# @tool/@BaseTool).  The AST scanner will never find a source declaration for
# these, so they appear as "ghost" entries without this exemption.
SCHEMA_ONLY_TOOL_NAMES: frozenset[str] = frozenset({
    "dispatch_research",   # Deep Research orchestrator state-machine signal
    "finalize_report",     # Deep Research orchestrator state-machine signal
    "think",               # Deep Research orchestrator state-machine signal
})

CROSS_MODULE_CONSTANTS: dict[str, str] = {
    "CONVERSATION_SEARCH_TOOL_NAME": "conversation_search_tool",
    "TOOL_NAME": "skill_analyze_tool",
}

# Each whitelisted factory ships as an opt-in toolkit: the harness exports it
# via `myrm_agent_harness.toolkits.<name>` (or lazy `__getattr__`), and business
# code wires it in only when needed. Static grep cannot follow lazy imports,
# so they look like orphans without this allow-list.
ORPHAN_FACTORY_WHITELIST: frozenset[str] = frozenset({
    "create_desktop_tools",     # Desktop / computer-use opt-in toolkit
    "create_browser_tools",          # Browser automation opt-in toolkit
    "create_skill_select_tool",      # Built dynamically by SkillAgent depending on skill count
    "create_huggingface_inference_tool",  # Lazy-loaded via toolkits/__init__::_LAZY_IMPORTS
    "create_automation_tools",       # Optional automation toolkit
    "create_calendar_tools",         # Optional calendar toolkit
    "create_kanban_tools",           # Optional kanban toolkit
    "create_channel_notify_tool",
    "create_conversation_search_tool",
    "create_cron_tools",
    "create_delegate_to_agent_tool",
    "create_goal_tools",
    "create_image_search_tool",
    "create_local_browser_data_tool",
    "create_memory_tools",
})

BOOTSTRAP_FILES: frozenset[str] = frozenset({
    "myrm-agent-server/app/ai_agents/general_agent/tools/_tool_layer_bootstrap.py",
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
