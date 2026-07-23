"""Architecture gate for sub_agents/types.py import boundaries.

`agent/sub_agents/types.py` is imported early by delegate/subagent paths.
If it depends on `agent.meta_tools`, Python package initialization can re-enter
`meta_tools.__init__` and recreate circular import failures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.boundary_engine import collect_imports

_TYPES_FILE = _REPO_ROOT / "src" / "myrm_agent_harness" / "agent" / "sub_agents" / "types.py"
_FORBIDDEN_PREFIX = "myrm_agent_harness.agent.meta_tools"
_CANONICAL_SSOT_MODULES = {
    "myrm_agent_harness.agent.sub_agents.hitl_tool_policy",
    "hitl_tool_policy",
}


@pytest.mark.architecture
def test_sub_agents_types_has_no_meta_tools_dependency() -> None:
    imports = collect_imports(_TYPES_FILE)
    rel = _TYPES_FILE.relative_to(_REPO_ROOT)
    violations = [
        f"{rel}:{lineno} imports {module}"
        for lineno, module in imports
        if module == _FORBIDDEN_PREFIX or module.startswith(f"{_FORBIDDEN_PREFIX}.")
    ]
    if violations:
        msg = "sub_agents/types.py must not import agent.meta_tools.*:\n" + "\n".join(violations)
        raise AssertionError(msg)


@pytest.mark.architecture
def test_sub_agents_types_imports_hitl_policy_from_sub_agents_ssot() -> None:
    imports = collect_imports(_TYPES_FILE)
    has_canonical_ssot = any(module in _CANONICAL_SSOT_MODULES for _lineno, module in imports)
    assert has_canonical_ssot, (
        "sub_agents/types.py must import HITL policy from "
        "agent/sub_agents/hitl_tool_policy.py (canonical SSOT)."
    )
