from unittest.mock import patch

from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import _format_result, _get_os_hint


def test_get_os_hint():
    with patch("platform.system", return_value="Linux"):
        hint = _get_os_hint()
        assert "Linux" in hint
        assert "GNU" in hint


def test_format_result_stderr_only():
    res, _is_trunc, _meta = _format_result({"exit_code": 1, "stderr": "error msg"}, "cmd")
    assert "[stderr]" in res
    assert "error msg" in res


def test_format_result_invalid_exit_code():
    res, _is_trunc, _meta = _format_result({"exit_code": "invalid", "stdout": "ok"}, "cmd")
    assert "ok" in res


def test_format_result_empty():
    res, _is_trunc, _meta = _format_result({"exit_code": 0}, "cmd")
    assert "(no output)" in res
