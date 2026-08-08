"""Architecture guard: bash path must not re-introduce Turn1 native PTC stubs."""

from __future__ import annotations

from pathlib import Path

_HARNESS_ROOT = Path(__file__).resolve().parents[2]
_META_TOOLS_INIT = _HARNESS_ROOT / "src/myrm_agent_harness/agent/meta_tools/__init__.py"
_BASH_CODE_EXECUTE = _HARNESS_ROOT / "src/myrm_agent_harness/agent/meta_tools/bash/bash_code_execute_tool.py"
_PREPARE_MIXIN = _HARNESS_ROOT / "src/myrm_agent_harness/agent/meta_tools/bash/bash_executor_prepare_mixin.py"


def test_meta_tools_must_not_extend_ptc_tools_ref() -> None:
    source = _META_TOOLS_INIT.read_text(encoding="utf-8")
    assert "_ptc_tools_ref" not in source
    assert "ptc_tools=" not in source


def test_bash_code_execute_tool_has_static_description_only() -> None:
    source = _BASH_CODE_EXECUTE.read_text(encoding="utf-8")
    assert "get_ptc_description" not in source
    assert "ptc_tools" not in source


def test_bash_prepare_mixin_must_not_inject_turn1_ptc() -> None:
    source = _PREPARE_MIXIN.read_text(encoding="utf-8")
    assert "inject_ptc_for_python_execution" not in source
    assert "_execute_python_with_ptc" not in source
    assert "_ptc_tools" not in source
