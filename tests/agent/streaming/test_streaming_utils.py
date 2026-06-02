"""streaming/utils.py 全面测试

覆盖：AGENT_BEHAVIOR_RULES 常量、set_user_timezone、set_datetime_injection_enabled、
get_datetime_prompt 无效时区分支、validate_context、normalize_tool_names。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.streaming.utils import (
    AGENT_BEHAVIOR_RULES,
    DATETIME_SYSTEM_RULES,
    DATETIME_TAG,
    DATETIME_TAG_END,
    datetime_injection_enabled_var,
    get_datetime_prompt,
    normalize_tool_names,
    set_datetime_injection_enabled,
    set_user_timezone,
    user_timezone_var,
    validate_context,
)


class TestAgentBehaviorRules:
    """AGENT_BEHAVIOR_RULES 常量内容校验"""

    def test_wrapped_in_xml_tags(self) -> None:
        assert "<agent_behavior_rules>" in AGENT_BEHAVIOR_RULES
        assert "</agent_behavior_rules>" in AGENT_BEHAVIOR_RULES

    def test_anti_narration_keywords(self) -> None:
        assert "NEVER narrate" in AGENT_BEHAVIOR_RULES
        assert "FINAL ANSWER" in AGENT_BEHAVIOR_RULES

    def test_bilingual_examples(self) -> None:
        assert "让我查一下" in AGENT_BEHAVIOR_RULES
        assert "搜索中" in AGENT_BEHAVIOR_RULES
        assert "I will use" in AGENT_BEHAVIOR_RULES

    def test_self_correction(self) -> None:
        assert "NEVER output <tool_call>" in AGENT_BEHAVIOR_RULES

    def test_tool_honesty_keywords(self) -> None:
        assert "NEVER fabricate" in AGENT_BEHAVIOR_RULES
        assert "No results found" in AGENT_BEHAVIOR_RULES
        assert "report the error" in AGENT_BEHAVIOR_RULES

    def test_starts_with_newline(self) -> None:
        assert AGENT_BEHAVIOR_RULES.startswith("\n")

    def test_is_static_string(self) -> None:
        assert AGENT_BEHAVIOR_RULES is AGENT_BEHAVIOR_RULES
        assert isinstance(AGENT_BEHAVIOR_RULES, str)

    def test_datetime_rules_also_static(self) -> None:
        assert "<datetime_rules>" in DATETIME_SYSTEM_RULES
        assert "</datetime_rules>" in DATETIME_SYSTEM_RULES


class TestContextVarSetters:
    """set_user_timezone / set_datetime_injection_enabled"""

    def test_set_user_timezone(self) -> None:
        set_user_timezone("America/New_York")
        assert user_timezone_var.get() == "America/New_York"
        set_user_timezone(None)
        assert user_timezone_var.get() is None

    def test_set_datetime_injection_enabled(self) -> None:
        set_datetime_injection_enabled(False)
        assert datetime_injection_enabled_var.get() is False
        set_datetime_injection_enabled(True)
        assert datetime_injection_enabled_var.get() is True


class TestGetDatetimePromptEdgeCases:
    """get_datetime_prompt 边界分支"""

    def test_invalid_timezone_fallback(self) -> None:
        prompt = get_datetime_prompt(
            timezone="Invalid/Timezone", dt=datetime(2026, 5, 1, 12, 0)
        )
        assert DATETIME_TAG in prompt
        assert DATETIME_TAG_END in prompt
        assert "2026-05-01" in prompt

    def test_no_timezone_no_dt(self) -> None:
        prompt = get_datetime_prompt()
        assert prompt.startswith(DATETIME_TAG)
        assert prompt.endswith(DATETIME_TAG_END)

    def test_half_hour_offset_timezone(self) -> None:
        prompt = get_datetime_prompt(
            timezone="Asia/Kolkata", dt=datetime(2026, 5, 1, 12, 0)
        )
        assert "UTC+5:30" in prompt


class TestValidateContext:
    """validate_context 全分支覆盖"""

    def test_no_schema_no_context(self) -> None:
        result = validate_context(None, None)
        assert result == {}

    def test_no_schema_with_context(self) -> None:
        ctx = {"key": "value"}
        result = validate_context(ctx, None)
        assert result == ctx

    def test_dataclass_schema_valid(self) -> None:
        @dataclasses.dataclass
        class MyCtx:
            name: str
            count: int

        result = validate_context({"name": "test", "count": 5}, MyCtx)
        assert result == {"name": "test", "count": 5}

    def test_dataclass_schema_missing_context(self) -> None:
        @dataclasses.dataclass
        class MyCtx:
            name: str

        with pytest.raises(ValueError, match="context is required"):
            validate_context(None, MyCtx)

    def test_dataclass_schema_wrong_fields(self) -> None:
        @dataclasses.dataclass
        class MyCtx:
            name: str

        with pytest.raises(ValueError, match="Context validation failed"):
            validate_context({"wrong": "field"}, MyCtx)

    def test_regular_class_schema(self) -> None:
        class MyCtx:
            annotations: ClassVar[dict[str, type]] = {"name": str}

            def __init__(self, name: str) -> None:
                self.name = name

        result = validate_context({"name": "hello"}, MyCtx)
        assert result["name"] == "hello"

    def test_schema_generic_exception(self) -> None:
        class BadSchema:
            def __init__(self, **_: object) -> None:
                raise RuntimeError("init error")

        with pytest.raises(
            ValueError, match="Context validation failed for schema BadSchema"
        ):
            validate_context({"a": 1}, BadSchema)


class TestNormalizeToolNames:
    """normalize_tool_names 全分支覆盖"""

    def test_already_suffixed(self) -> None:
        tool = MagicMock(spec=BaseTool)
        tool.name = "search_tool"
        result = normalize_tool_names([tool])
        assert len(result) == 1
        assert result[0].name == "search_tool"

    def test_auto_suffix(self) -> None:
        tool = MagicMock(spec=BaseTool)
        tool.name = "search"
        result = normalize_tool_names([tool])
        assert len(result) == 1
        assert result[0].name == "search_tool"

    def test_skip_non_basetool(self) -> None:
        result = normalize_tool_names(["not_a_tool"])  # type: ignore[list-item]
        assert len(result) == 0

    def test_mixed_input(self) -> None:
        valid = MagicMock(spec=BaseTool)
        valid.name = "my_tool"
        result = normalize_tool_names([valid, "bad", valid])  # type: ignore[list-item]
        assert len(result) == 2

    def test_meta_tool_exempt_from_suffix(self) -> None:
        tool = MagicMock(spec=BaseTool)
        tool.name = "discover_capability_tool"
        result = normalize_tool_names([tool])
        assert len(result) == 1
        assert result[0].name == "discover_capability_tool"

    def test_empty_list(self) -> None:
        result = normalize_tool_names([])
        assert result == []
