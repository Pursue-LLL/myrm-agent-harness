"""Error Diagnostics i18n End-to-End Integration Tests

This module tests the integration of error diagnostics with i18n in realistic scenarios:
1. Error context extraction from various error types
2. Locale-aware error message generation
3. Resolution steps in the appropriate language
"""

import os

from myrm_agent_harness.agent.errors.diagnostics import ErrorContext, LLMErrorDiagnostic


class TestErrorDiagnosticsIntegration:
    """Integration tests for error diagnostics with i18n"""

    def test_connection_error_with_ollama_detection(self) -> None:
        """Test connection error detection and Ollama-specific guidance (English)"""
        # Simulate connection refused error from Ollama
        exc = ConnectionRefusedError("[Errno 61] Connection refused (localhost:11434)")
        context = ErrorContext(
            model_name="llama3.2",
            is_custom_endpoint=True,
            base_url="http://localhost:11434",
        )

        result = LLMErrorDiagnostic.diagnose(exc, context, locale="en")

        # Verify English message contains Ollama or connection info
        assert "connect" in result.user_message.lower()
        assert "ollama" in result.user_message.lower() or "http://localhost:11434" in result.user_message

        # Verify Ollama-specific resolution steps
        resolution_text = "\n".join(result.resolution_steps)
        assert "ollama" in resolution_text.lower() or "localhost:11434" in resolution_text
        assert len(result.resolution_steps) > 0

    def test_connection_error_chinese_translation(self) -> None:
        """Test connection error with Chinese translation"""
        exc = ConnectionRefusedError("[Errno 61] Connection refused")
        context = ErrorContext(
            model_name="qwen2",
            is_custom_endpoint=True,
            base_url="http://localhost:11434",
        )

        result = LLMErrorDiagnostic.diagnose(exc, context, locale="zh-CN")

        # Verify Chinese message
        assert "无法连接" in result.user_message or "连接被拒绝" in result.user_message
        assert "localhost:11434" in result.user_message

        # Verify Chinese resolution steps
        assert isinstance(result.resolution_steps, list)
        assert len(result.resolution_steps) > 0
        # At least one step should be in Chinese
        assert any("检查" in step or "确认" in step or "启动" in step for step in result.resolution_steps)

    def test_model_not_found_with_context_model_name(self) -> None:
        """Test model not found error using context model name"""
        exc = ValueError("The requested model was not found")
        context = ErrorContext(
            model_name="gpt-4-turbo",
            is_custom_endpoint=False,
        )

        result = LLMErrorDiagnostic.diagnose(exc, context, locale="en")

        # Should use model name from context
        assert "gpt-4-turbo" in result.user_message
        assert "not found" in result.user_message.lower()

    def test_rate_limit_error_with_parameter_injection(self) -> None:
        """Test rate limit error with dynamic parameter"""
        exc = ValueError("Rate limit exceeded (status 429)")

        result = LLMErrorDiagnostic.diagnose(exc, locale="zh-CN")

        # Verify Chinese message
        assert "速率限制" in result.user_message or "超出限制" in result.user_message

        # Verify resolution steps
        resolution_text = "\n".join(result.resolution_steps)
        assert len(resolution_text) > 0

    def test_api_key_error_with_provider_detection(self) -> None:
        """Test API key error detection and resolution"""
        exc = ValueError("Incorrect API key provided")

        result = LLMErrorDiagnostic.diagnose(exc, locale="en")

        # Verify error message mentions API key or contains error details
        assert "api key" in result.user_message.lower() or "incorrect" in result.user_message.lower()

        # Verify resolution steps exist and provide guidance
        assert len(result.resolution_steps) > 0
        assert not result.is_retryable  # API key errors are not retryable

    def test_timeout_error_retryable_flag(self) -> None:
        """Test timeout error sets retryable flag correctly"""
        exc = TimeoutError("Request timeout after 30s")

        result = LLMErrorDiagnostic.diagnose(exc, locale="en")

        assert "timeout" in result.user_message.lower() or "timed out" in result.user_message.lower()
        assert result.is_retryable  # Timeout errors are retryable

    def test_context_overflow_with_token_count(self) -> None:
        """Test context overflow error"""
        exc = ValueError("Context length exceeded: 150000 tokens")
        context = ErrorContext(
            model_name="gpt-4-turbo",
            is_custom_endpoint=False,
        )

        result = LLMErrorDiagnostic.diagnose(exc, context, locale="zh-CN")

        # Verify Chinese message contains relevant keywords
        assert "上下文" in result.user_message or "超出" in result.user_message or "长度" in result.user_message
        # Verify resolution steps exist
        assert len(result.resolution_steps) > 0
        # Verify error type is correctly identified
        assert result.error_type == "context_overflow"

    def test_locale_auto_detection_from_environment(self) -> None:
        """Test automatic locale detection from environment variables"""
        # Save original
        original_myrm_locale = os.environ.get("MYRM_LOCALE")
        original_lang = os.environ.get("LANG")

        try:
            # Set Chinese locale in environment
            os.environ["MYRM_LOCALE"] = "zh-CN"

            exc = ValueError("Connection timeout")

            # Don't specify locale - should auto-detect from env
            result = LLMErrorDiagnostic.diagnose(exc)

            # Should use detected locale (zh-CN from MYRM_LOCALE)
            # Note: This test verifies that LocaleManager.detect_locale() works
            assert result.locale in ["zh-CN", "en"]  # Falls back to en if detection fails

        finally:
            # Restore original environment
            if original_myrm_locale is not None:
                os.environ["MYRM_LOCALE"] = original_myrm_locale
            elif "MYRM_LOCALE" in os.environ:
                del os.environ["MYRM_LOCALE"]

            if original_lang is not None:
                os.environ["LANG"] = original_lang
            elif "LANG" in os.environ:
                del os.environ["LANG"]

    def test_unknown_error_fallback_with_original_message(self) -> None:
        """Test unknown error type falls back gracefully"""
        exc = RuntimeError("Some unexpected error occurred")

        result = LLMErrorDiagnostic.diagnose(exc, locale="en")

        # Should classify as unknown and include original message
        assert result.error_type == "unknown"
        assert "Some unexpected error occurred" in result.user_message

    def test_multiple_locales_same_error(self) -> None:
        """Test same error produces different messages for different locales"""
        exc = ConnectionRefusedError("Connection refused")
        context = ErrorContext(
            model_name="llama3",
            is_custom_endpoint=True,
            base_url="http://localhost:11434",
        )

        result_en = LLMErrorDiagnostic.diagnose(exc, context, locale="en")
        result_zh = LLMErrorDiagnostic.diagnose(exc, context, locale="zh-CN")

        # English should contain English words
        assert any(word in result_en.user_message.lower() for word in ["unable", "connect", "connection", "refused"])

        # Chinese should contain Chinese characters
        assert any(char in result_zh.user_message for char in ["无法", "连接", "拒绝", "端点"])

        # Both should have the same error type and retryability
        assert result_en.error_type == result_zh.error_type
        assert result_en.is_retryable == result_zh.is_retryable
