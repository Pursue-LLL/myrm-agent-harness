from myrm_agent_harness.agent.meta_tools.file_ops.file_read_truncation import truncate_file_output as _truncate_file_output


def test_truncate_file_output_no_truncation():
    output = "short text"
    truncated, was_truncated, meta = _truncate_file_output(output, max_chars=100)
    assert truncated == "short text"
    assert was_truncated is False
    assert meta == {}

def test_truncate_file_output_with_truncation():
    output = "a" * 200
    truncated, was_truncated, meta = _truncate_file_output(output, max_chars=100, is_dir=False, path_str="test.txt")
    assert was_truncated is True
    assert "SYSTEM WARNING" in truncated
    assert meta["type"] == "file"
    assert meta["path"] == "test.txt"
    assert meta["total_lines"] == 1
    assert meta["shown_chars"] == 100
    assert "total_mb" in meta

    assert "start_line/end_line" in truncated
    assert "grep" not in truncated
    assert "bash_exec" not in truncated

def test_truncate_file_output_includes_actual_path_in_hint():
    """Line range example in hint must include the actual file path."""
    output = "a" * 200
    truncated, _, _ = _truncate_file_output(output, max_chars=100, is_dir=False, path_str="src/app.py")
    assert "src/app.py:100-200" in truncated


def test_truncate_file_output_at_exact_boundary():
    """Output exactly at max_chars should not be truncated."""
    output = "a" * 100
    truncated, was_truncated, meta = _truncate_file_output(output, max_chars=100)
    assert was_truncated is False
    assert truncated == output
    assert meta == {}


def test_truncate_dir_output_with_truncation():
    output = "a" * 200
    truncated, was_truncated, meta = _truncate_file_output(output, max_chars=100, is_dir=True, path_str="test_dir")
    assert was_truncated is True
    assert "truncated" in truncated
    assert meta["type"] == "dir"
    assert meta["path"] == "test_dir"
