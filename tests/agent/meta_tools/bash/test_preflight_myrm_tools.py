"""Preflight checks for bash myrm_tools guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.meta_tools.bash._security.preflight_checks import check_myrm_tools_import
from myrm_agent_harness.utils.errors import ToolError


def test_myrm_tools_import_blocked_in_python() -> None:
    with pytest.raises(ToolError, match="myrm_tools") as exc_info:
        check_myrm_tools_import('import myrm_tools\nprint("x")')
    assert exc_info.value.error_code == "MYRM_TOOLS_BLOCKED"
    assert exc_info.value.diagnostic_info.get("error_category") == ToolErrorCategory.GUARDRAIL_BLOCKED.value


def test_myrm_tools_attribute_access_blocked_in_python() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import("myrm_tools.file_read_tool(path='/x')")


def test_myrm_tools_from_import_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import("from myrm_tools import session_store")


def test_myrm_tools_guard_ignores_benign_shell_commands() -> None:
    check_myrm_tools_import("ls -la")
    check_myrm_tools_import("echo myrm_tools.foo")
    check_myrm_tools_import("grep myrm_tools /var/log/app.log")


def test_myrm_tools_guard_allows_python_string_literal() -> None:
    check_myrm_tools_import('label = "myrm_tools.foo"\nprint(label)')


def test_bash_c_import_myrm_tools_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import('bash -c "import myrm_tools"')


def test_sh_c_myrm_tools_attribute_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import("sh -c 'myrm_tools.file_read_tool(\"/x\")'")


def test_python_c_import_myrm_tools_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import('python -c "import myrm_tools"')


def test_myrm_tools_shell_import_line_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import("import myrm_tools")


def test_myrm_tools_referenced_python_file_blocked(tmp_path: Path) -> None:
    script_path = tmp_path / "run.py"
    script_path.write_text("import myrm_tools\nprint('x')\n", encoding="utf-8")

    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import("python run.py", workspace_root=str(tmp_path))


def test_myrm_tools_referenced_workspace_python_file_blocked(tmp_path: Path) -> None:
    script_path = tmp_path / "run.py"
    script_path.write_text("myrm_tools.notify('x')\n", encoding="utf-8")

    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import(
            "python /workspace/run.py",
            workspace_root=str(tmp_path),
        )


def test_myrm_tools_referenced_python_file_allows_clean_script(tmp_path: Path) -> None:
    script_path = tmp_path / "run.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")

    check_myrm_tools_import("python run.py", workspace_root=str(tmp_path))


def test_myrm_tools_referenced_python_file_skips_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_myrm_scan.py"
    outside.write_text("import myrm_tools\n", encoding="utf-8")

    check_myrm_tools_import(f"python {outside}", workspace_root=str(tmp_path))


def test_myrm_tools_pipe_stdin_import_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools") as exc_info:
        check_myrm_tools_import('printf "import myrm_tools" | python3')
    assert exc_info.value.error_code == "MYRM_TOOLS_BLOCKED"
    assert exc_info.value.diagnostic_info.get("error_category") == ToolErrorCategory.GUARDRAIL_BLOCKED.value


def test_myrm_tools_pipe_stdin_echo_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import("echo 'from myrm_tools import x' | python3")


def test_myrm_tools_pipe_stdin_skills_import_allowed() -> None:
    check_myrm_tools_import('echo "from skills.mcp_x import foo" | python3')


def test_myrm_tools_pipe_stdin_python_c_still_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import('python -c "import myrm_tools"')


def test_myrm_tools_pipe_stdin_unquoted_echo_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import("echo import myrm_tools | python3")


def test_myrm_tools_python_m_module_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools") as exc_info:
        check_myrm_tools_import("python3 -m myrm_tools")
    assert exc_info.value.error_code == "MYRM_TOOLS_BLOCKED"
    assert exc_info.value.error_category == "guardrail_blocked"


def test_myrm_tools_python_m_submodule_blocked() -> None:
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import("python3 -m myrm_tools.notify")


def test_myrm_tools_python_m_pip_allowed() -> None:
    check_myrm_tools_import("python3 -m pip install requests")


def test_myrm_tools_cat_pipe_python_file_blocked(tmp_path: Path) -> None:
    script_path = tmp_path / "merge.py"
    script_path.write_text("import myrm_tools\nprint('x')\n", encoding="utf-8")
    with pytest.raises(ToolError, match="myrm_tools") as exc_info:
        check_myrm_tools_import(f"cat {script_path} | python3", workspace_root=str(tmp_path))
    assert exc_info.value.error_code == "MYRM_TOOLS_BLOCKED"


def test_myrm_tools_env_cat_pipe_python_file_blocked(tmp_path: Path) -> None:
    script_path = tmp_path / "merge.py"
    script_path.write_text("import myrm_tools\n", encoding="utf-8")
    with pytest.raises(ToolError, match="myrm_tools"):
        check_myrm_tools_import(
            f"env cat {script_path} | python3",
            workspace_root=str(tmp_path),
        )


def test_myrm_tools_cat_pipe_clean_file_allowed(tmp_path: Path) -> None:
    script_path = tmp_path / "clean.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")
    check_myrm_tools_import(f"cat {script_path} | python3", workspace_root=str(tmp_path))


def test_myrm_tools_cat_pipe_to_grep_not_scanned(tmp_path: Path) -> None:
    script_path = tmp_path / "evil.py"
    script_path.write_text("import myrm_tools\n", encoding="utf-8")
    check_myrm_tools_import(f"cat {script_path} | grep myrm_tools", workspace_root=str(tmp_path))


def test_myrm_tools_oversized_referenced_python_file_skipped(tmp_path: Path) -> None:
    from myrm_agent_harness.agent.meta_tools.bash._security.preflight_checks import (
        _MAX_REFERENCED_PY_SCAN_BYTES,
    )

    script_path = tmp_path / "big.py"
    script_path.write_bytes(b"import myrm_tools\n" + b"#" * (_MAX_REFERENCED_PY_SCAN_BYTES + 1))
    check_myrm_tools_import(f"python3 {script_path.name}", workspace_root=str(tmp_path))


def test_myrm_tools_cat_pipe_missing_file_allowed() -> None:
    check_myrm_tools_import("cat /tmp/nonexistent_myrm_guard_test.py | python3")


def test_myrm_tools_referenced_python_file_read_error_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_path = tmp_path / "unreadable.py"
    script_path.write_text("import myrm_tools\n", encoding="utf-8")

    def _raise_os_error(*_args: object, **_kwargs: object) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", _raise_os_error)
    check_myrm_tools_import(f"python3 {script_path.name}", workspace_root=str(tmp_path))


def test_myrm_tools_block_hint_routes_to_correct_apis() -> None:
    with pytest.raises(ToolError) as exc_info:
        check_myrm_tools_import("import myrm_tools")
    hint = exc_info.value.user_hint
    assert hint is not None
    assert "MYRM_PROGRESS" in hint
    assert "workspace" in hint.lower() or "json" in hint.lower()
    assert "session_store" not in hint
    assert "skills" in hint
    assert "file_read_tool" in hint
