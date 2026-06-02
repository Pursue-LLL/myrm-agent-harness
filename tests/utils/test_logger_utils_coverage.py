"""Tests for logger_utils - covering all AgentLogger methods."""

from myrm_agent_harness.utils.logger_utils import (
    AgentLogger,
    get_agent_core_logger,
    get_agent_logger,
    get_skill_logger,
)


class TestAgentLogger:
    def setup_method(self):
        self.logger = get_agent_logger("test")

    def test_step(self):
        self.logger.step("Processing query", query="test")

    def test_success(self):
        self.logger.success("Done", count=5)

    def test_info(self):
        self.logger.info("Info message", key="value")

    def test_warn(self):
        self.logger.warn("Warning message", threshold=100)

    def test_error(self):
        self.logger.error("Error occurred", code=500)

    def test_error_detail(self):
        try:
            raise ValueError("test error")
        except ValueError as e:
            self.logger.error_detail("Failed", error=e, context="test")

    def test_prune(self):
        self.logger.prune("Context pruned", removed=5, total=10, strategy="aggressive")

    def test_prune_no_strategy(self):
        self.logger.prune("Pruned", removed=3, total=8)

    def test_token_count_with_total(self):
        self.logger.token_count("Step 1", tokens=150, total_tokens=300)

    def test_token_count_without_total(self):
        self.logger.token_count("Step 1", tokens=150)

    def test_decision(self):
        self.logger.decision("Use web search", reason="User asked a factual question", confidence=0.9)

    def test_separator_with_title(self):
        self.logger.separator("Section 1")

    def test_separator_without_title(self):
        self.logger.separator()

    def test_debug(self):
        self.logger.debug("Debug message")

    def test_warning(self):
        self.logger.warning("Warning message")


class TestFormatKwargs:
    def setup_method(self):
        self.logger = get_agent_logger("test")

    def test_empty_kwargs(self):
        result = self.logger._format_kwargs({})
        assert result == ""

    def test_simple_kwargs(self):
        result = self.logger._format_kwargs({"key": "value"})
        assert "key=value" in result

    def test_long_string_truncation(self):
        result = self.logger._format_kwargs({"key": "x" * 200})
        assert "..." in result

    def test_messages_kwarg(self):
        class MockMsg:
            content = "hello"
            tool_calls = None
            tool_call_id = None
            id = "msg-1"

        result = self.logger._format_kwargs({"messages": [MockMsg()]})
        assert "msg-1" in result
        assert "hello" in result

    def test_messages_with_tool_calls(self):
        class MockMsg:
            content = "test"
            tool_calls = [{"id": "tc1"}]
            tool_call_id = "tc1"
            id = "msg-2"

        result = self.logger._format_kwargs({"messages": [MockMsg()]})
        assert "tool_calls" in result
        assert "tool_call_id" in result

    def test_messages_long_content_truncation(self):
        class MockMsg:
            content = "x" * 300
            tool_calls = None
            tool_call_id = None
            id = ""

        result = self.logger._format_kwargs({"messages": [MockMsg()]})
        assert "..." in result

    def test_format_messages_empty(self):
        result = self.logger._format_messages([])
        assert result == "[]"


class TestFactoryFunctions:
    def test_get_agent_logger(self):
        logger = get_agent_logger("test.module")
        assert isinstance(logger, AgentLogger)

    def test_get_skill_logger(self):
        logger = get_skill_logger("web_search")
        assert isinstance(logger, AgentLogger)

    def test_get_agent_core_logger(self):
        logger = get_agent_core_logger("context")
        assert isinstance(logger, AgentLogger)
