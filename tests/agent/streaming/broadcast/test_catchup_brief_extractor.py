"""Unit tests for CatchupBriefExtractor.

Verifies that the extractor correctly produces structured summaries
from raw message + progress-step data for the Catchup Inbox feature.
"""

from myrm_agent_harness.agent.streaming.broadcast.catchup import (
    CatchupBrief,
    CatchupBriefExtractor,
)


class TestCatchupBriefDefaults:
    """Empty inputs should produce safe defaults."""

    def test_empty_inputs(self) -> None:
        brief = CatchupBriefExtractor.extract([], [], status="completed")
        assert isinstance(brief, CatchupBrief)
        assert brief.last_user_prompt == ""
        assert brief.latest_agent_response == ""
        assert brief.files_touched == []
        assert brief.tool_counts == {}
        assert brief.activity_steps == []
        assert brief.needs_from_user is None
        assert brief.status == "completed"


class TestMessageExtraction:
    """Tests for extracting user/assistant content from messages."""

    def test_extracts_last_user_prompt(self) -> None:
        messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"},
        ]
        brief = CatchupBriefExtractor.extract(messages, [])
        assert brief.last_user_prompt == "Second question"

    def test_extracts_latest_agent_response(self) -> None:
        messages = [
            {"role": "user", "content": "Do something"},
            {"role": "assistant", "content": "Done with task A"},
            {"role": "assistant", "content": "Done with task B"},
        ]
        brief = CatchupBriefExtractor.extract(messages, [])
        assert brief.latest_agent_response == "Done with task B"

    def test_skips_empty_content(self) -> None:
        messages = [
            {"role": "user", "content": "Real question"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "   "},
            {"role": "assistant", "content": "Real answer"},
        ]
        brief = CatchupBriefExtractor.extract(messages, [])
        assert brief.last_user_prompt == "Real question"
        assert brief.latest_agent_response == "Real answer"

    def test_handles_non_string_content(self) -> None:
        messages = [
            {"role": "user", "content": 123},
            {"role": "user", "content": "Valid question"},
            {"role": "assistant", "content": None},
            {"role": "assistant", "content": "Valid answer"},
        ]
        brief = CatchupBriefExtractor.extract(messages, [])
        assert brief.last_user_prompt == "Valid question"
        assert brief.latest_agent_response == "Valid answer"


class TestProgressStepExtraction:
    """Tests for extracting tool counts, files, and activity steps."""

    def test_counts_tools(self) -> None:
        steps = [
            {"tool_name": "file_write_tool", "items": [{"path": "a.py"}]},
            {"tool_name": "file_write_tool", "items": [{"path": "b.py"}]},
            {"tool_name": "bash_code_execute_tool", "items": [{"command": "ls"}]},
        ]
        brief = CatchupBriefExtractor.extract([], steps)
        assert brief.tool_counts == {"file_write_tool": 2, "bash_code_execute_tool": 1}

    def test_extracts_file_paths(self) -> None:
        steps = [
            {"tool_name": "file_write_tool", "items": [{"path": "src/main.py"}]},
            {"tool_name": "file_edit_tool", "items": [{"path": "src/utils.py"}]},
            {"tool_name": "file_replace_tool", "items": [{"path": "src/main.py"}]},
            {"tool_name": "file_patch_tool", "items": [{"path": "tests/test.py"}]},
        ]
        brief = CatchupBriefExtractor.extract([], steps)
        assert sorted(brief.files_touched) == ["src/main.py", "src/utils.py", "tests/test.py"]

    def test_extracts_bash_activity(self) -> None:
        steps = [
            {"tool_name": "bash_code_execute_tool", "items": [{"command": "npm install"}]},
        ]
        brief = CatchupBriefExtractor.extract([], steps)
        assert len(brief.activity_steps) == 1
        assert "Ran command: npm install" in brief.activity_steps[0]

    def test_extracts_shell_activity(self) -> None:
        steps = [
            {"tool_name": "shell_tool", "items": [{"command": "pip install requests"}]},
        ]
        brief = CatchupBriefExtractor.extract([], steps)
        assert len(brief.activity_steps) == 1
        assert "Ran command: pip install requests" in brief.activity_steps[0]

    def test_truncates_long_commands(self) -> None:
        long_cmd = "a" * 100
        steps = [{"tool_name": "bash_code_execute_tool", "items": [{"command": long_cmd}]}]
        brief = CatchupBriefExtractor.extract([], steps)
        assert brief.activity_steps[0].endswith("...")

    def test_extracts_web_search_activity(self) -> None:
        steps = [
            {"tool_name": "web_search_tool", "items": [{"query": "Python asyncio tutorial"}]},
        ]
        brief = CatchupBriefExtractor.extract([], steps)
        assert "Searched web for: Python asyncio tutorial" in brief.activity_steps[0]

    def test_deduplicates_activity_steps(self) -> None:
        steps = [
            {"tool_name": "bash_code_execute_tool", "items": [{"command": "npm test"}]},
            {"tool_name": "bash_code_execute_tool", "items": [{"command": "npm test"}]},
            {"tool_name": "bash_code_execute_tool", "items": [{"command": "npm test"}]},
        ]
        brief = CatchupBriefExtractor.extract([], steps)
        assert len(brief.activity_steps) == 1

    def test_limits_activity_steps_to_five(self) -> None:
        steps = [
            {"tool_name": "bash_code_execute_tool", "items": [{"command": f"cmd-{i}"}]}
            for i in range(10)
        ]
        brief = CatchupBriefExtractor.extract([], steps)
        assert len(brief.activity_steps) <= 5

    def test_ignores_invalid_tool_names(self) -> None:
        steps = [
            {"tool_name": "", "items": []},
            {"tool_name": None, "items": []},
            {"items": [{"path": "a.py"}]},
            {"tool_name": 123, "items": []},
        ]
        brief = CatchupBriefExtractor.extract([], steps)
        assert brief.tool_counts == {}

    def test_ignores_invalid_items(self) -> None:
        steps = [
            {"tool_name": "file_write_tool", "items": None},
            {"tool_name": "file_write_tool", "items": "not-a-list"},
            {"tool_name": "file_write_tool", "items": [None, "string", 42]},
        ]
        brief = CatchupBriefExtractor.extract([], steps)
        assert brief.files_touched == []


class TestNeedsFromUser:
    """Tests for inferring needs_from_user based on status and content."""

    def test_waiting_for_approval(self) -> None:
        brief = CatchupBriefExtractor.extract([], [], status="waiting_for_approval")
        assert brief.needs_from_user is not None
        assert "approval" in brief.needs_from_user.lower()

    def test_error_status(self) -> None:
        brief = CatchupBriefExtractor.extract([], [], status="error")
        assert brief.needs_from_user is not None
        assert "error" in brief.needs_from_user.lower()

    def test_question_detection(self) -> None:
        messages = [
            {"role": "assistant", "content": "Should I proceed with the refactor?"},
        ]
        brief = CatchupBriefExtractor.extract(messages, [])
        assert brief.needs_from_user is not None
        assert "question" in brief.needs_from_user.lower()

    def test_no_needs_for_completed(self) -> None:
        messages = [
            {"role": "assistant", "content": "All done."},
        ]
        brief = CatchupBriefExtractor.extract(messages, [])
        assert brief.needs_from_user is None


class TestIntegration:
    """End-to-end test combining messages and progress steps."""

    def test_full_scenario(self) -> None:
        messages = [
            {"role": "user", "content": "Refactor the auth module"},
            {"role": "assistant", "content": "Starting refactor..."},
            {"role": "assistant", "content": "Refactoring complete. 3 files updated."},
        ]
        steps = [
            {"tool_name": "file_edit_tool", "items": [{"path": "auth/login.py"}]},
            {"tool_name": "file_edit_tool", "items": [{"path": "auth/logout.py"}]},
            {"tool_name": "file_write_tool", "items": [{"path": "auth/middleware.py"}]},
            {"tool_name": "bash_code_execute_tool", "items": [{"command": "pytest tests/"}]},
            {"tool_name": "web_search_tool", "items": [{"query": "JWT best practices"}]},
        ]
        brief = CatchupBriefExtractor.extract(messages, steps, status="completed")

        assert brief.last_user_prompt == "Refactor the auth module"
        assert brief.latest_agent_response == "Refactoring complete. 3 files updated."
        assert len(brief.files_touched) == 3
        assert "auth/login.py" in brief.files_touched
        assert brief.tool_counts["file_edit_tool"] == 2
        assert brief.tool_counts["file_write_tool"] == 1
        assert brief.tool_counts["bash_code_execute_tool"] == 1
        assert brief.tool_counts["web_search_tool"] == 1
        assert any("pytest" in s for s in brief.activity_steps)
        assert any("JWT" in s for s in brief.activity_steps)
        assert brief.needs_from_user is None
        assert brief.status == "completed"
