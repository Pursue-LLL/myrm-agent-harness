"""测试时间戳注入功能 — 确保星期几信息正确注入，以及多模态时间戳注入"""

from contextvars import copy_context
from datetime import datetime

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.streaming.message_builder import (
    _inject_datetime_into_multimodal,
    inject_datetime_tags,
)
from myrm_agent_harness.agent.streaming.utils import (
    DATETIME_FORMAT,
    DATETIME_TAG,
    datetime_injection_enabled_var,
    get_datetime_prompt,
    user_timezone_var,
)


class TestDatetimeInjection:
    """测试时间戳注入功能"""

    def test_datetime_format_includes_weekday(self) -> None:
        """验证时间格式包含星期几信息（%A）"""
        assert "%A" in DATETIME_FORMAT, "DATETIME_FORMAT must include %A (full weekday name)"

    def test_get_datetime_prompt_includes_weekday(self) -> None:
        """验证生成的时间提示词包含星期几"""
        test_date = datetime(2026, 4, 13, 17, 13)
        prompt = get_datetime_prompt(timezone=None, dt=test_date)

        assert "Monday" in prompt, f"Expected 'Monday' in prompt, got: {prompt}"
        assert "2026-04-13 17:13 Monday" in prompt, f"Expected full datetime with weekday, got: {prompt}"

    def test_get_datetime_prompt_with_timezone(self) -> None:
        """验证带时区的时间提示词包含星期几"""
        test_date = datetime(2026, 4, 13, 17, 13)
        prompt = get_datetime_prompt(timezone="Asia/Shanghai", dt=test_date)

        assert "Monday" in prompt, f"Expected 'Monday' in prompt, got: {prompt}"
        assert "UTC+8" in prompt, f"Expected 'UTC+8' in prompt, got: {prompt}"

    @pytest.mark.parametrize(
        "year,month,day,expected_weekday",
        [
            (2026, 4, 13, "Monday"),
            (2026, 4, 12, "Sunday"),
            (2026, 4, 14, "Tuesday"),
            (2026, 4, 11, "Saturday"),
        ],
    )
    def test_correct_weekday_for_various_dates(self, year: int, month: int, day: int, expected_weekday: str) -> None:
        """验证不同日期的星期几都正确"""
        test_date = datetime(year, month, day, 12, 0)
        prompt = get_datetime_prompt(timezone=None, dt=test_date)

        assert expected_weekday in prompt, (
            f"Expected '{expected_weekday}' for {year}-{month:02d}-{day:02d}, got: {prompt}"
        )

    def test_get_datetime_prompt_format_structure(self) -> None:
        """验证时间提示词的格式结构"""
        test_date = datetime(2026, 4, 13, 17, 13)
        prompt = get_datetime_prompt(timezone="Asia/Shanghai", dt=test_date)

        assert prompt.startswith("<current_datetime>"), "Prompt should start with <current_datetime> tag"
        assert prompt.endswith("</current_datetime>"), "Prompt should end with </current_datetime> tag"
        assert "2026-04-13" in prompt, "Prompt should contain date"
        assert "17:13" in prompt, "Prompt should contain time"
        assert "Monday" in prompt, "Prompt should contain weekday"
        assert "UTC+8" in prompt, "Prompt should contain timezone offset"

    def test_weekday_regression_case(self) -> None:
        """回归测试：验证原始bug场景（2026-04-13应该是Monday，不是Sunday）"""
        bug_date = datetime(2026, 4, 13, 17, 13)
        prompt = get_datetime_prompt(timezone="Asia/Shanghai", dt=bug_date)

        assert "Monday" in prompt, (
            "2026-04-13 is Monday, not Sunday. This was the original bug - AI incorrectly said 'Sunday'"
        )
        assert "Sunday" not in prompt, f"2026-04-13 should not be Sunday, got: {prompt}"


class TestMultimodalDatetimeInjection:
    """Tests for multimodal (list) query datetime injection."""

    def _run_with_injection_enabled(self, fn):
        """Helper to run fn with datetime injection context vars set."""
        ctx = copy_context()
        def _inner():
            datetime_injection_enabled_var.set(True)
            user_timezone_var.set("UTC")
            fn()
        ctx.run(_inner)

    def test_multimodal_text_part_gets_datetime(self) -> None:
        """Datetime is appended to the first text part of a multimodal query."""
        query: list[dict[str, object]] = [
            {"type": "text", "text": "Describe this image"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
        ]
        messages = [HumanMessage(content=query)]

        def _test():
            inject_datetime_tags(messages, None, query)
            content = messages[-1].content
            assert isinstance(content, list)
            text_part = content[0]
            assert DATETIME_TAG in str(text_part.get("text", ""))
            assert content[1]["type"] == "image_url"

        self._run_with_injection_enabled(_test)

    def test_multimodal_preserves_image_parts(self) -> None:
        """Image parts are not modified during datetime injection."""
        img_url = "data:image/png;base64,xyz"
        query: list[dict[str, object]] = [
            {"type": "text", "text": "What do you see?"},
            {"type": "image_url", "image_url": {"url": img_url}},
        ]
        messages = [HumanMessage(content=query)]

        def _test():
            inject_datetime_tags(messages, None, query)
            content = messages[-1].content
            assert isinstance(content, list)
            assert len(content) == 2
            assert content[1]["image_url"]["url"] == img_url

        self._run_with_injection_enabled(_test)

    def test_multimodal_already_has_datetime_tag(self) -> None:
        """No double injection when text already contains DATETIME_TAG."""
        existing_text = f"Already tagged {DATETIME_TAG} content"
        query: list[dict[str, object]] = [
            {"type": "text", "text": existing_text},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
        ]
        messages = [HumanMessage(content=query)]

        def _test():
            inject_datetime_tags(messages, None, query)
            content = messages[-1].content
            assert isinstance(content, list)
            assert content[0]["text"] == existing_text

        self._run_with_injection_enabled(_test)

    def test_multimodal_multiple_text_parts_only_first_injected(self) -> None:
        """Only the first text part receives datetime injection."""
        query: list[dict[str, object]] = [
            {"type": "text", "text": "First text"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
            {"type": "text", "text": "Second text"},
        ]
        messages = [HumanMessage(content=query)]

        def _test():
            inject_datetime_tags(messages, None, query)
            content = messages[-1].content
            assert isinstance(content, list)
            assert DATETIME_TAG in str(content[0].get("text", ""))
            assert content[2]["text"] == "Second text"

        self._run_with_injection_enabled(_test)

    def test_inject_datetime_into_multimodal_helper_directly(self) -> None:
        """Direct test of _inject_datetime_into_multimodal helper."""
        query: list[dict[str, object]] = [
            {"type": "text", "text": "Hello"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/"}},
        ]
        messages: list = [HumanMessage(content=query)]
        datetime_prompt = "<current_datetime>2026-05-22 23:00 Friday (UTC)</current_datetime>"

        _inject_datetime_into_multimodal(messages, query, datetime_prompt)

        content = messages[-1].content
        assert isinstance(content, list)
        assert "Hello" in str(content[0]["text"])
        assert datetime_prompt in str(content[0]["text"])
        assert content[1]["type"] == "image_url"

    def test_plain_text_injection_still_works(self) -> None:
        """Ensures plain text query injection is not broken."""
        query = "Simple question"
        messages = [HumanMessage(content=query)]

        def _test():
            inject_datetime_tags(messages, None, query)
            content = messages[-1].content
            assert isinstance(content, str)
            assert DATETIME_TAG in content
            assert "Simple question" in content

        self._run_with_injection_enabled(_test)
