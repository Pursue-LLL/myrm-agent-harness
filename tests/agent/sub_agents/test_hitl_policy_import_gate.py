import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_HARNESS_ROOT = Path(__file__).resolve().parents[3]
_SRC_PATH = _HARNESS_ROOT / "src"
_CANONICAL_MODULE = "myrm_agent_harness.agent.sub_agents.hitl_tool_policy"


def _run_import_smoke(script: str) -> None:
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(_SRC_PATH)
        if not current_pythonpath
        else f"{_SRC_PATH}{os.pathsep}{current_pythonpath}"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_HARNESS_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"import smoke failed with exit={completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def test_import_order_clarification_then_types_works_and_is_single_ssot():
    script = textwrap.dedent(
        f"""
        import myrm_agent_harness.agent.meta_tools.clarification as clarification
        import myrm_agent_harness.agent.sub_agents.types as types_mod
        from {_CANONICAL_MODULE} import HITL_TOOL_POLICY as canonical_policy
        from {_CANONICAL_MODULE} import HitlToolPolicy as canonical_type

        assert clarification.HITL_TOOL_POLICY is canonical_policy
        assert types_mod.HITL_TOOL_POLICY is canonical_policy
        assert clarification.HitlToolPolicy is canonical_type
        assert clarification.HITL_TOOL_POLICY.__class__.__module__ == "{_CANONICAL_MODULE}"
        """
    )
    _run_import_smoke(script)


def test_import_order_types_then_clarification_works_and_is_single_ssot():
    script = textwrap.dedent(
        f"""
        import myrm_agent_harness.agent.sub_agents.types as types_mod
        import myrm_agent_harness.agent.meta_tools.clarification as clarification
        from {_CANONICAL_MODULE} import HITL_TOOL_POLICY as canonical_policy
        from {_CANONICAL_MODULE} import HitlToolPolicy as canonical_type

        assert types_mod.HITL_TOOL_POLICY is canonical_policy
        assert clarification.HITL_TOOL_POLICY is canonical_policy
        assert clarification.HitlToolPolicy is canonical_type
        assert clarification.HITL_TOOL_POLICY.__class__.__module__ == "{_CANONICAL_MODULE}"
        """
    )
    _run_import_smoke(script)


def test_legacy_shim_path_removed_and_unimportable():
    legacy_path = (
        _HARNESS_ROOT
        / "src"
        / "myrm_agent_harness"
        / "agent"
        / "meta_tools"
        / "clarification"
        / "hitl_tool_policy.py"
    )
    assert not legacy_path.exists()
    with pytest.raises(ModuleNotFoundError):
        __import__("myrm_agent_harness.agent.meta_tools.clarification.hitl_tool_policy")
