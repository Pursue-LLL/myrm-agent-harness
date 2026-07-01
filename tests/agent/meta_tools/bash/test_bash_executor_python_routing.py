"""Integration tests: BashExecutor._prepare_execution routes via toolkits code_detector."""

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.bash.bash_executor import (
    BashExecutionError,
    BashExecutor,
)


@pytest.fixture
def bash_executor() -> BashExecutor:
    mock_code_executor = MagicMock()
    mock_code_executor.config = MagicMock()
    return BashExecutor(mock_code_executor, enable_skill_execution=False)


class TestPrepareExecutionPythonRouting:
    def test_bash_command_stays_bash_mode(self, bash_executor: BashExecutor) -> None:
        use_python, prepared, mcp = bash_executor._prepare_execution("ls -la")
        assert use_python is False
        assert prepared == "ls -la"
        assert mcp is None

    def test_python_c_extracts_and_enables_python_mode(self, bash_executor: BashExecutor) -> None:
        use_python, prepared, mcp = bash_executor._prepare_execution('python3 -c "print(1)"')
        assert use_python is True
        assert prepared == "print(1)"
        assert mcp is None
        assert bash_executor.consume_python_c_transform_hint() is not None

    def test_multiline_python_enables_python_mode(self, bash_executor: BashExecutor) -> None:
        code = "import os\nimport sys\n\ndef main():\n    pass\nmain()"
        use_python, prepared, _ = bash_executor._prepare_execution(code)
        assert use_python is True
        assert prepared == code

    def test_invalid_python_raises_before_executor(self, bash_executor: BashExecutor) -> None:
        with pytest.raises(BashExecutionError) as exc_info:
            bash_executor._prepare_execution('python3 -c "def broken("')
        assert exc_info.value.phase == "preparation"

    def test_await_async_python(self, bash_executor: BashExecutor) -> None:
        use_python, prepared, _ = bash_executor._prepare_execution("result = await fetch()")
        assert use_python is True
        assert "await" in prepared

    def test_mcp_timeout_floor_applied(self, bash_executor: BashExecutor) -> None:
        from myrm_agent_harness.agent.meta_tools.bash.bash_executor_constants import MCP_MIN_TIMEOUT

        assert bash_executor._maybe_extend_timeout_for_mcp([object()], 30) == MCP_MIN_TIMEOUT
        assert bash_executor._maybe_extend_timeout_for_mcp(None, 600) == 600
