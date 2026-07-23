"""Tests for step_builder module — build_step_data and _inject_diff."""

import pytest

from myrm_agent_harness.agent.streaming.step_builder import (
    build_step_data,
    get_step_key,
    _inject_diff,
)


class TestGetStepKey:
    def test_override_keys(self):
        assert get_step_key("file_read_tool") == "file_read_tool"
        assert get_step_key("file_write_tool") == "file_write_tool"
        assert get_step_key("file_edit_tool") == "file_edit_tool"
        assert get_step_key("bash_code_execute_tool") == "bash_code_execute_tool_tool"

    def test_default_suffix(self):
        assert get_step_key("web_search") == "web_search_tool"
        assert get_step_key("custom_tool") == "custom_tool_tool"


class TestBuildStepDataSearch:
    def test_glob_tool_pattern(self) -> None:
        result = build_step_data("glob_tool", {"pattern": "**/*.py", "path": "src"})
        assert result["step_key"] == "glob_tool"
        assert result["data"] == [{"pattern": "**/*.py", "search_path": "src"}]

    def test_grep_tool_pattern(self) -> None:
        result = build_step_data(
            "grep_tool",
            {"pattern": "def main", "path": ".", "file_pattern": "**/*.py"},
        )
        assert result["step_key"] == "grep_tool"
        assert result["data"][0]["pattern"] == "def main"
        assert result["data"][0]["file_pattern"] == "**/*.py"

    def test_search_with_query(self):
        result = build_step_data("web_search", {"query": "hello world"})
        assert result == {"data": [{"query": "hello world"}]}

    def test_search_with_questions_list(self):
        result = build_step_data("deep_search", {"questions": ["q1", "q2"]})
        assert result == {"data": [{"query": "q1"}, {"query": "q2"}]}

    def test_search_truncates_to_5(self):
        qs = [f"q{i}" for i in range(10)]
        result = build_step_data("search_tool", {"questions": qs})
        assert len(result["data"]) == 5


class TestBuildStepDataFetch:
    def test_fetch_with_url(self):
        result = build_step_data("webpage_fetch", {"url": "https://example.com"})
        assert result == {"data": [{"url": "https://example.com"}]}

    def test_fetch_with_urls_list(self):
        result = build_step_data("browse_tool", {"urls": ["u1", "u2"]})
        assert result == {"data": [{"url": "u1"}, {"url": "u2"}]}


class TestBuildStepDataFileWrite:
    def test_file_write_basic(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("print('hello')")
        result = build_step_data("file_write_tool", {"path": str(f), "content": "print('hello')"})
        assert result["step_key"] == "file_write_tool"
        assert len(result["data"]) == 1
        item = result["data"][0]
        assert item["file_path"] == str(f)
        assert item["action_type"] == "write"
        assert "diff" in item
        assert "+print('hello')" in item["diff"]

    def test_file_write_no_path(self):
        result = build_step_data("file_write_tool", {"path": "", "content": "x"})
        assert result == {"data": []}

    def test_file_write_no_content(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = build_step_data("file_write_tool", {"path": str(f), "content": ""})
        item = result["data"][0]
        assert "diff" not in item


class TestBuildStepDataFileEdit:
    def test_file_edit_with_diff(self, tmp_path):
        f = tmp_path / "edit.py"
        f.write_text("old content")
        result = build_step_data("file_edit_tool", {
            "path": str(f),
            "old_str": "old content",
            "new_str": "new content",
        })
        assert result["step_key"] == "file_edit_tool"
        item = result["data"][0]
        assert item["action_type"] == "write"
        assert "diff" in item
        assert "-old content" in item["diff"]
        assert "+new content" in item["diff"]

    def test_file_edit_no_old_new(self, tmp_path):
        f = tmp_path / "noop.py"
        f.write_text("x")
        result = build_step_data("file_edit_tool", {"path": str(f), "old_str": "", "new_str": ""})
        item = result["data"][0]
        assert "diff" not in item

    def test_file_edit_batch_edits_diff(self, tmp_path):
        f = tmp_path / "batch.py"
        f.write_text("line_a\nline_b\nline_c\n")
        result = build_step_data(
            "file_edit_tool",
            {
                "path": str(f),
                "edits": [
                    {"old_str": "line_a", "new_str": "LINE_A"},
                    {"old_str": "line_c", "new_str": "LINE_C"},
                ],
            },
        )
        item = result["data"][0]
        assert "diff" in item
        assert "--- edit 1 ---" in item["diff"]
        assert "--- edit 2 ---" in item["diff"]
        assert "-line_a" in item["diff"]
        assert "+LINE_A" in item["diff"]


class TestBuildStepDataBash:
    def test_bash_code_execute(self):
        result = build_step_data("bash_code_execute_tool", {"command": "ls -la"})
        assert result["step_key"] == "bash_code_execute_tool_tool"
        assert result["data"] == [{"code": "ls -la"}]


class TestInjectDiff:
    def test_basic_diff(self):
        item: dict[str, str | bool] = {"file_path": "test.py"}
        _inject_diff(item, "test.py", "old\n", "new\n")
        assert "diff" in item
        assert "-old" in item["diff"]
        assert "+new" in item["diff"]

    def test_empty_strings_noop(self):
        item: dict[str, str | bool] = {"file_path": "test.py"}
        _inject_diff(item, "test.py", "", "")
        assert "diff" not in item

    def test_truncation(self):
        old_lines = "".join(f"line{i}\n" for i in range(100))
        new_lines = "".join(f"changed{i}\n" for i in range(100))
        item: dict[str, str | bool] = {"file_path": "big.py"}
        _inject_diff(item, "big.py", old_lines, new_lines)
        assert item.get("diff_truncated") is True
        # _DIFF_MAX_LINES=50 limits the number of diff_lines before join
        # After join, the actual rendered string may have more visual lines
        # due to keepends=True in splitlines, but the source list is capped at 50
        assert "diff" in item
        assert len(item["diff"]) < len(old_lines) + len(new_lines)

    def test_new_file_diff(self):
        item: dict[str, str | bool] = {"file_path": "new.py"}
        _inject_diff(item, "new.py", "", "line1\nline2\n")
        assert "diff" in item
        assert "+line1" in item["diff"]
        assert "+line2" in item["diff"]
        assert item.get("diff_truncated") is not True


class TestBuildStepDataSkillSelect:
    def test_skill_select(self):
        result = build_step_data("skill_select_tool", {
            "skill_names": ["code_review", "debug"],
            "reason": "Need help",
        })
        assert len(result["data"]) == 2
        assert result["data"][0] == {"skill_name": "code_review", "reason": "Need help"}


class TestBuildStepDataFileRead:
    def test_file_read(self, tmp_path):
        f = tmp_path / "read.txt"
        f.write_text("content")
        result = build_step_data("file_read_tool", {"paths": [str(f)]})
        assert result["step_key"] == "file_read_tool"
        item = result["data"][0]
        assert item["file_path"] == str(f)
        assert item["action_type"] == "read"
        assert "size_bytes" in item

    def test_file_read_json_string_paths(self, tmp_path):
        import json
        f = tmp_path / "a.txt"
        f.write_text("x")
        result = build_step_data("file_read_tool", {"paths": json.dumps([str(f)])})
        assert result["step_key"] == "file_read_tool"
        assert result["data"][0]["file_path"] == str(f)

    def test_file_read_invalid_json_string(self):
        result = build_step_data("file_read_tool", {"paths": "not-json-at-all"})
        assert result["step_key"] == "file_read_tool"
        assert result["data"][0]["file_path"] == "not-json-at-all"

    def test_file_read_nonexistent_file(self):
        result = build_step_data("file_read_tool", {"paths": ["/nonexistent/xyz.py"]})
        item = result["data"][0]
        assert item["file_path"] == "/nonexistent/xyz.py"
        assert "size_bytes" not in item

    def test_file_read_empty_paths(self):
        result = build_step_data("file_read_tool", {"paths": []})
        # empty paths falls through to generic "other tool" summary
        assert "data" in result


class TestBuildStepDataFileEditEdgeCases:
    def test_file_edit_empty_path(self):
        result = build_step_data("file_edit_tool", {"path": "", "old_str": "x", "new_str": "y"})
        assert result == {"data": []}

    def test_file_edit_nonexistent_file(self):
        result = build_step_data("file_edit_tool", {
            "path": "/nonexistent/foo.py",
            "old_str": "a",
            "new_str": "b",
        })
        item = result["data"][0]
        assert "size_bytes" not in item
        assert "diff" in item

    def test_file_write_nonexistent_file(self):
        result = build_step_data("file_write_tool", {
            "path": "/nonexistent/bar.py",
            "content": "hello",
        })
        item = result["data"][0]
        assert "size_bytes" not in item
        assert "diff" in item


class TestBuildStepDataGenericFileCode:
    def test_generic_file_tool_with_path(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        result = build_step_data("file_viewer_tool", {"path": str(f)})
        item = result["data"][0]
        assert item["file_path"] == str(f)
        assert item["action_type"] == "read"
        assert "size_bytes" in item

    def test_generic_file_tool_write_action(self, tmp_path):
        f = tmp_path / "out.py"
        f.write_text("")
        result = build_step_data("file_write_append", {"path": str(f)})
        item = result["data"][0]
        assert item["action_type"] == "write"

    def test_generic_file_tool_search_action(self):
        result = build_step_data("file_grep_search", {"path": "/some/path"})
        item = result["data"][0]
        assert item["action_type"] == "search"

    def test_generic_file_tool_with_line_range(self, tmp_path):
        f = tmp_path / "lr.py"
        f.write_text("a\nb\nc")
        result = build_step_data("file_inspect_tool", {"path": str(f), "start_line": 1, "end_line": 10})
        item = result["data"][0]
        assert item["line_range"] == "1-10"

    def test_generic_file_tool_start_line_only(self, tmp_path):
        f = tmp_path / "sl.py"
        f.write_text("x")
        result = build_step_data("code_reader", {"path": str(f), "start_line": 5})
        item = result["data"][0]
        assert item["line_range"] == "5-"

    def test_generic_code_tool_with_code_no_path(self):
        result = build_step_data("execute_shell", {"code": "echo hello world"})
        item = result["data"][0]
        assert "text" in item
        assert "echo hello world" in item["text"]

    def test_generic_code_tool_long_snippet(self):
        long_code = "x" * 200
        result = build_step_data("shell_exec", {"command": long_code})
        item = result["data"][0]
        assert item["text"].endswith("...")
        assert len(item["text"]) <= 104  # " " prefix + 100 chars + "..."


class TestBuildStepDataOtherTools:
    def test_other_tool_summary(self):
        result = build_step_data("calendar_tool", {"date": "2024-01-01", "title": "Meeting"})
        item = result["data"][0]
        assert "text" in item
        assert "date:" in item["text"]
        assert "title:" in item["text"]

    def test_other_tool_skips_reason(self):
        result = build_step_data("memory_tool", {"key": "val", "reason": "skip this"})
        item = result["data"][0]
        assert "reason:" not in item["text"]
        assert "key:" in item["text"]

    def test_other_tool_long_value_truncation(self):
        result = build_step_data("note_tool", {"content": "a" * 200})
        item = result["data"][0]
        assert "..." in item["text"]

    def test_empty_args(self):
        result = build_step_data("unknown_tool", {})
        assert result == {"data": []}


class TestInjectDiffEdgeCases:
    def test_identical_strings_no_diff(self):
        item: dict[str, str | bool] = {"file_path": "same.py"}
        _inject_diff(item, "same.py", "same content\n", "same content\n")
        assert "diff" not in item
