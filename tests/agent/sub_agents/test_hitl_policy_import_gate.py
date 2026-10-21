import os
import subprocess
import sys
import textwrap
from pathlib import Path

_HARNESS_ROOT = Path(__file__).resolve().parents[3]
_SRC_PATH = _HARNESS_ROOT / "src"
_CANONICAL_MODULE = "myrm_agent_harness.agent.sub_agents.hitl_tool_policy"


def _run_import_smoke(script: str) -> None:
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC_PATH) if not current_pythonpath else f"{_SRC_PATH}{os.pathsep}{current_pythonpath}"
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


def test_canonical_import_works():
    """Canonical SSOT path imports correctly and returns frozen singleton."""
    script = textwrap.dedent(
        f"""
        from {_CANONICAL_MODULE} import HITL_TOOL_POLICY, HitlToolPolicy
        assert isinstance(HITL_TOOL_POLICY, HitlToolPolicy)
        assert HITL_TOOL_POLICY.__class__.__module__ == "{_CANONICAL_MODULE}"
        assert "ask_question_tool" in HITL_TOOL_POLICY.registered_tools
        """
    )
    _run_import_smoke(script)


def test_types_module_reexports_canonical_ssot():
    """sub_agents.types re-exports the same singleton from canonical SSOT."""
    script = textwrap.dedent(
        f"""
        import myrm_agent_harness.agent.sub_agents.types as types_mod
        from {_CANONICAL_MODULE} import HITL_TOOL_POLICY as canonical_policy

        assert types_mod.HITL_TOOL_POLICY is canonical_policy
        """
    )
    _run_import_smoke(script)


def test_legacy_shim_removed():
    """The backward-compat shim in clarification/ must not exist (dead code cleanup)."""
    legacy_path = (
        _HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "meta_tools" / "clarification" / "hitl_tool_policy.py"
    )
    assert not legacy_path.exists(), (
        "Backward-compat shim must be removed; import HitlToolPolicy directly from agent.sub_agents.hitl_tool_policy"
    )
