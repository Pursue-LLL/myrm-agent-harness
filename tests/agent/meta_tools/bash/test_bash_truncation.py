from myrm_agent_harness.agent.meta_tools.bash.bash_tool import _format_result, _truncate_bash_output


def test_truncate_bash_output_no_truncation():
    output = "short text"
    truncated, was_truncated, meta = _truncate_bash_output(output, max_chars=100)
    assert truncated == "short text"
    assert was_truncated is False
    assert meta == {}


def test_truncate_bash_output_with_truncation():
    output = "a" * 200
    truncated, was_truncated, meta = _truncate_bash_output(output, max_chars=100)
    assert was_truncated is True
    assert "SYSTEM WARNING" in truncated
    assert "skipped" in truncated
    assert meta["type"] == "bash"
    assert meta["total_lines"] == 1
    assert meta["shown_chars"] == 100
    assert "total_mb" in meta

    assert "file_read_tool" in truncated
    assert "grep" not in truncated


def test_truncate_bash_output_preserves_head_and_tail():
    """Middle truncation must preserve first and last portions."""
    output = "HEAD_MARKER" + "x" * 200 + "TAIL_MARKER"
    truncated, was_truncated, _ = _truncate_bash_output(output, max_chars=100)
    assert was_truncated is True
    assert "HEAD_MARKER" in truncated
    assert "TAIL_MARKER" in truncated


def test_truncate_bash_output_at_exact_boundary():
    """Output exactly at max_chars should not be truncated."""
    output = "a" * 100
    truncated, was_truncated, meta = _truncate_bash_output(output, max_chars=100)
    assert was_truncated is False
    assert truncated == output
    assert meta == {}


def test_format_result_with_truncation():
    result_dict = {"stdout": "a" * 10000, "exit_code": "0"}
    formatted, was_truncated, meta = _format_result(result_dict, "echo a")
    assert was_truncated is True
    assert meta["type"] == "bash"
    assert "SYSTEM WARNING" in formatted
