"""Core tests for myrm_agent_harness.utils.errors (ToolError, formatting, model output validation)."""

from __future__ import annotations

import logging

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.utils.errors import (
    ModelOutputValidator,
    ToolError,
    format_error_message,
    log_and_format_error,
)


class TestToolError:
    def test_message_only(self) -> None:
        err = ToolError("technical failure")
        assert str(err) == "technical failure"
        assert err.user_hint == ""

    def test_with_user_hint(self) -> None:
        err = ToolError("technical failure", user_hint="Retry with smaller input.")
        assert err.user_hint == "Retry with smaller input."


class TestFormatErrorMessage:
    def test_basic(self) -> None:
        msg = format_error_message(ValueError("bad value"))
        assert "ValueError" in msg
        assert "bad value" in msg

    def test_with_context(self) -> None:
        msg = format_error_message(RuntimeError("x"), context="unit")
        assert msg.startswith("unit - ")
        assert "RuntimeError" in msg

    def test_empty_str_uses_repr(self) -> None:
        class EmptyMessageError(Exception):
            def __str__(self) -> str:
                return ""

        msg = format_error_message(EmptyMessageError())
        assert "EmptyMessageError" in msg

    def test_include_traceback(self) -> None:
        try:
            raise KeyError("missing")
        except KeyError as exc:
            msg = format_error_message(exc, include_traceback=True)
        assert "Stack trace" in msg


class TestLogAndFormatError:
    def test_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        out = log_and_format_error(OSError("disk"), context="io")
        assert "io" in out
        assert "OSError" in out
        assert any("io" in r.message for r in caplog.records)


class TestModelOutputValidator:
    def test_string_output(self) -> None:
        r = ModelOutputValidator.validate_model_output("hello")
        assert r["has_content"] is True
        assert r["is_valid"] is True
        assert r["extracted_text"] == "hello"
        assert r["error_msg"] is None

    def test_empty_string_invalid(self) -> None:
        r = ModelOutputValidator.validate_model_output("   ")
        assert r["has_content"] is False
        assert r["is_valid"] is False
        assert r["error_msg"] is not None

    def test_ai_message_string_content(self) -> None:
        m = AIMessage(content="ok")
        r = ModelOutputValidator.validate_model_output(m)
        assert r["extracted_text"] == "ok"
        assert r["has_content"] is True

    def test_ai_message_list_content(self) -> None:
        m = AIMessage(content=["a", "b"])
        r = ModelOutputValidator.validate_model_output(m)
        assert "a" in r["extracted_text"] and "b" in r["extracted_text"]

    def test_ai_message_with_tool_calls_valid_without_text(self) -> None:
        m = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1", "type": "tool_call"}])
        r = ModelOutputValidator.validate_model_output(m)
        assert r["has_tool_calls"] is True
        assert r["is_valid"] is True

    def test_arbitrary_object_with_tool_calls(self) -> None:
        class Obj:
            tool_calls = [{"x": 1}]

        r = ModelOutputValidator.validate_model_output(Obj())
        assert r["has_tool_calls"] is True

    def test_create_model_capability_error(self) -> None:
        err = ModelOutputValidator.create_model_capability_error()
        assert isinstance(err, RuntimeError)
        assert "tool invocation" in str(err).lower()

    def test_human_message_branch(self) -> None:
        r = ModelOutputValidator.validate_model_output(HumanMessage(content="hi"))
        assert r["extracted_text"] == "hi"
        assert r["has_content"] is True

    def test_validation_exception_path(self) -> None:
        class Exploding:
            def __str__(self) -> str:
                raise RuntimeError("boom")

        r = ModelOutputValidator.validate_model_output(Exploding())
        assert r["is_valid"] is False
        assert r["error_msg"] is not None
        assert "validation failed" in r["error_msg"].lower()
