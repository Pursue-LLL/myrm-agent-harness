"""Tests for summary_parser module."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.strategies.summary_parser import (
    extract_existing_summary,
    extract_messages_after_summary,
    format_messages_for_summary,
    parse_summary_response,
)


class TestExtractExistingSummary:
    def test_detects_pipeline_summary_zh(self) -> None:
        msgs = [SystemMessage(content="[历史摘要]\n用户目标: 修bug")]
        result = extract_existing_summary(msgs)
        assert result is not None
        assert result.user_goal == "修bug"

    def test_detects_persistent_summary_en(self) -> None:
        msgs = [AIMessage(content="[Previous conversation summary]\n用户目标: refactor")]
        result = extract_existing_summary(msgs)
        assert result is not None
        assert result.user_goal == "refactor"

    def test_returns_none_when_no_summary(self) -> None:
        msgs = [HumanMessage(content="hello"), AIMessage(content="hi")]
        assert extract_existing_summary(msgs) is None

    def test_json_block_takes_priority(self) -> None:
        summary = StructuredSummary(user_goal="build feature", completed_actions=["step1"], key_findings=["found X"])
        content = f"[历史摘要]\n用户目标: old goal\n<!-- SUMMARY_JSON\n{summary.to_json()}\n-->"
        msgs = [SystemMessage(content=content)]
        result = extract_existing_summary(msgs)
        assert result is not None
        assert result.user_goal == "build feature"
        assert result.completed_actions == ["step1"]

    def test_non_string_content_handled(self) -> None:
        msgs = [SystemMessage(content=["[历史摘要]", "用户目标: test"])]
        result = extract_existing_summary(msgs)
        assert result is None or isinstance(result, StructuredSummary)


class TestExtractMessagesAfterSummary:
    def test_returns_messages_after_summary(self) -> None:
        msgs = [
            SystemMessage(content="[历史摘要]\n用户目标: foo"),
            HumanMessage(content="new question"),
            AIMessage(content="new answer"),
        ]
        result = extract_messages_after_summary(msgs)
        assert len(result) == 2
        assert isinstance(result[0], HumanMessage)

    def test_returns_all_when_no_summary(self) -> None:
        msgs = [HumanMessage(content="hello"), AIMessage(content="hi")]
        result = extract_messages_after_summary(msgs)
        assert len(result) == 2

    def test_persistent_summary_marker(self) -> None:
        msgs = [
            AIMessage(content="[Previous conversation summary]\ngoal"),
            HumanMessage(content="follow up"),
        ]
        result = extract_messages_after_summary(msgs)
        assert len(result) == 1


class TestFormatMessagesForSummary:
    def test_formats_human_messages(self) -> None:
        msgs = [HumanMessage(content="What is Python?")]
        result = format_messages_for_summary(msgs)
        assert "[用户]" in result
        assert "What is Python?" in result

    def test_formats_ai_text_reply(self) -> None:
        msgs = [AIMessage(content="Python is a language")]
        result = format_messages_for_summary(msgs)
        assert "[AI 回复]" in result

    def test_formats_ai_tool_calls(self) -> None:
        msg = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "tc1"}])
        result = format_messages_for_summary([msg])
        assert "[AI 调用工具]" in result
        assert "web_search" in result

    def test_formats_tool_message(self) -> None:
        msgs = [ToolMessage(content="result data", name="search", tool_call_id="tc1")]
        result = format_messages_for_summary(msgs)
        assert "[工具结果: search]" in result

    def test_skips_system_messages(self) -> None:
        msgs = [SystemMessage(content="system prompt")]
        result = format_messages_for_summary(msgs)
        assert result == ""

    def test_truncates_long_content(self) -> None:
        long_content = "x" * 1000
        msgs = [HumanMessage(content=long_content)]
        result = format_messages_for_summary(msgs)
        assert len(result) < len(long_content)

    def test_redacts_api_key_in_user_message(self) -> None:
        fake_key = "sk-" + "a1b2c3d4e5f6g7h8" * 4
        msgs = [HumanMessage(content=f"My key is {fake_key}")]
        result = format_messages_for_summary(msgs)
        assert fake_key not in result
        assert "[REDACTED:openai_key]" in result

    def test_redacts_database_url_in_tool_result(self) -> None:
        msgs = [ToolMessage(content="postgres://admin:secret@db.com:5432/prod", name="read_file", tool_call_id="tc1")]
        result = format_messages_for_summary(msgs)
        assert "secret" not in result
        assert "[REDACTED:database_url]" in result

    def test_preserves_normal_content(self) -> None:
        msgs = [HumanMessage(content="Help me write a Python function")]
        result = format_messages_for_summary(msgs)
        assert "Help me write a Python function" in result
        assert "REDACTED" not in result


class TestParseSummaryResponse:
    def test_parses_valid_json(self) -> None:
        data = {
            "user_goal": "build app",
            "completed_actions": ["step1", "step2"],
            "key_findings": ["found bug"],
            "files_modified": ["main.py"],
            "last_action": "fixed bug",
        }
        result = parse_summary_response(json.dumps(data))
        assert result.user_goal == "build app"
        assert result.completed_actions == ["step1", "step2"]
        assert result.key_findings == ["found bug"]
        assert result.files_modified == ["main.py"]
        assert result.last_action == "fixed bug"

    def test_extracts_json_from_mixed_content(self) -> None:
        content = 'Here is the summary: {"user_goal": "test", "completed_actions": []} done.'
        result = parse_summary_response(content)
        assert result.user_goal == "test"

    def test_handles_invalid_json(self) -> None:
        result = parse_summary_response("no json here at all")
        assert result.user_goal == "[摘要解析失败]"
        assert result.key_findings[0] == "no json here at all"

    def test_handles_list_input(self) -> None:
        result = parse_summary_response(["some", "list"])
        assert isinstance(result, StructuredSummary)

    def test_context_dump_path_passed(self) -> None:
        data = {"user_goal": "test"}
        result = parse_summary_response(json.dumps(data), context_dump_path="/tmp/dump.txt")
        assert result.context_dump_path == "/tmp/dump.txt"

    def test_missing_fields_use_defaults(self) -> None:
        result = parse_summary_response('{"user_goal": "minimal"}')
        assert result.completed_actions == []
        assert result.files_modified == []
        assert result.errors_and_fixes == []
        assert result.last_action == ""

    def test_parses_errors_and_fixes(self) -> None:
        data = {
            "user_goal": "fix bugs",
            "completed_actions": ["step1"],
            "key_findings": [],
            "errors_and_fixes": ["ImportError -> added missing import", "timeout -> increased deadline"],
            "files_modified": ["main.py"],
            "last_action": "fixed import",
        }
        result = parse_summary_response(json.dumps(data))
        assert result.errors_and_fixes == [
            "ImportError -> added missing import",
            "timeout -> increased deadline",
        ]

    def test_json_block_parses_errors_and_fixes(self) -> None:
        summary = StructuredSummary(user_goal="debug", errors_and_fixes=["crash -> null check"])
        content = f"[历史摘要]\n<!-- SUMMARY_JSON\n{summary.to_json()}\n-->"
        msgs = [SystemMessage(content=content)]
        result = extract_existing_summary(msgs)
        assert result is not None
        assert result.errors_and_fixes == ["crash -> null check"]

    def test_text_format_parses_errors_section(self) -> None:
        content = (
            "[历史摘要]\n"
            "用户目标: 修复bug\n"
            "已完成操作:\n"
            "  - 分析代码\n"
            "错误与修复:\n"
            "  - KeyError -> 添加默认值\n"
            "最后操作: 提交修复\n"
        )
        msgs = [SystemMessage(content=content)]
        result = extract_existing_summary(msgs)
        assert result is not None
        assert result.errors_and_fixes == ["KeyError -> 添加默认值"]

    def test_parses_handoff_fields_from_json(self) -> None:
        response = """<summary>
        {
            "user_goal": "重构模块",
            "active_task": "实现JWT认证",
            "constraints_and_preferences": ["用TypeScript"],
            "completed_actions": ["操作1"],
            "active_state": "dev分支",
            "key_findings": [],
            "errors_and_fixes": [],
            "resolved_questions": ["Q1 -> A1"],
            "pending_user_asks": ["待办1"],
            "files_modified": [],
            "last_action": "测试"
        }
        </summary>"""
        result = parse_summary_response(response)
        assert result.active_task == "实现JWT认证"
        assert result.constraints_and_preferences == ["用TypeScript"]
        assert result.active_state == "dev分支"
        assert result.resolved_questions == ["Q1 -> A1"]
        assert result.pending_user_asks == ["待办1"]

    def test_parses_handoff_fields_from_json_block(self) -> None:
        summary = StructuredSummary(
            user_goal="test",
            active_task="重构",
            constraints_and_preferences=["约束1"],
            resolved_questions=["Q -> A"],
            pending_user_asks=["待办"],
            active_state="main分支",
        )
        content = f"[历史摘要]\n<!-- SUMMARY_JSON\n{summary.to_json()}\n-->"
        msgs = [SystemMessage(content=content)]
        result = extract_existing_summary(msgs)
        assert result is not None
        assert result.active_task == "重构"
        assert result.constraints_and_preferences == ["约束1"]
        assert result.resolved_questions == ["Q -> A"]
        assert result.pending_user_asks == ["待办"]
        assert result.active_state == "main分支"

    def test_text_format_parses_new_sections(self) -> None:
        content = (
            "[历史摘要]\n"
            " 用户目标: 重构模块\n"
            " 当前任务: 实现认证\n"
            " 用户约束与偏好:\n"
            "  - 用TypeScript\n"
            "已完成操作:\n"
            "  - 操作1\n"
            " 已回答的问题:\n"
            "  - Q -> A\n"
            " 待完成请求:\n"
            "  - 待办1\n"
            " 工作状态: dev分支\n"
            " 最后操作: 测试\n"
        )
        msgs = [SystemMessage(content=content)]
        result = extract_existing_summary(msgs)
        assert result is not None
        assert result.active_task == "实现认证"
        assert result.constraints_and_preferences == ["用TypeScript"]
        assert result.resolved_questions == ["Q -> A"]
        assert result.pending_user_asks == ["待办1"]
        assert result.active_state == "dev分支"

    def test_missing_handoff_fields_default_empty(self) -> None:
        response = '{"user_goal": "test", "completed_actions": ["a"], "last_action": "b"}'
        result = parse_summary_response(response)
        assert result.active_task == ""
        assert result.constraints_and_preferences == []
        assert result.resolved_questions == []
        assert result.pending_user_asks == []
        assert result.active_state == ""

    def test_json_decode_error_fallback(self) -> None:
        response = "<summary>{invalid json here}</summary>"
        result = parse_summary_response(response)
        assert result.user_goal == "[摘要解析失败]"

    def test_raw_json_fallback(self) -> None:
        response = 'Some text {"user_goal": "raw", "completed_actions": [], "last_action": "x"} more text'
        result = parse_summary_response(response)
        assert result.user_goal == "raw"

    def test_summary_tag_without_closing(self) -> None:
        response = '<summary>{"user_goal": "no close", "completed_actions": [], "last_action": "x"}'
        result = parse_summary_response(response)
        assert result.user_goal == "no close"

    def test_summary_tag_no_json_inside(self) -> None:
        response = "<summary>no json here</summary>"
        result = parse_summary_response(response)
        assert result.user_goal == "[摘要解析失败]"

    def test_as_str_list_with_non_list(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary_parser import _as_str_list

        assert _as_str_list(None) == []
        assert _as_str_list("single") == ["single"]
        assert _as_str_list(42) == ["42"]
        assert _as_str_list(["a", "b"]) == ["a", "b"]

    def test_text_parse_no_user_goal_returns_none(self) -> None:
        content = "[历史摘要]\n已完成操作:\n  - 操作1\n"
        msgs = [SystemMessage(content=content)]
        result = extract_existing_summary(msgs)
        assert result is None

    def test_json_block_invalid_json(self) -> None:
        content = "[历史摘要]\n<!-- SUMMARY_JSON\n{bad json\n-->"
        msgs = [SystemMessage(content=content)]
        result = extract_existing_summary(msgs)
        assert result is None or result.user_goal != ""

    def test_text_parse_exception_returns_none(self) -> None:
        content = "[历史摘要]\n\x00\x01\x02"
        msgs = [SystemMessage(content=content)]
        result = extract_existing_summary(msgs)
        assert result is None
