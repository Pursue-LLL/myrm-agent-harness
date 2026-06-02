"""Test i18n integration for error diagnostics.

Tests cover:
- English/Chinese translation with explicit locale
- Automatic locale detection from environment
- Fallback to English for unsupported locales
- Template parameter interpolation for dynamic content
- All 9 error types (connection, api_key, model, rate_limit, context_overflow, timeout, custom_endpoint_unreachable, custom_model_not_found, unknown)
"""

import pytest

from myrm_agent_harness.agent.errors.diagnostics import ErrorContext, LLMErrorDiagnostic


class TestErrorDiagnosticsI18n:
    """Test i18n support in LLMErrorDiagnostic."""

    def test_english_translation(self) -> None:
        """Test English translation (explicit locale)."""
        exc = ConnectionError("Connection refused")
        context = ErrorContext(model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:11434")

        result = LLMErrorDiagnostic.diagnose(exc, context, locale="en")

        assert result.locale == "en"
        assert result.error_type == "custom_endpoint_unreachable"
        assert "Ollama" in result.user_message
        assert "http://localhost:11434" in result.user_message
        assert len(result.resolution_steps) > 0
        assert all(isinstance(step, str) for step in result.resolution_steps)

    def test_chinese_translation(self) -> None:
        """Test Chinese translation (explicit locale)."""
        exc = ConnectionError("Connection refused")
        context = ErrorContext(model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:11434")

        result = LLMErrorDiagnostic.diagnose(exc, context, locale="zh-CN")

        assert result.locale == "zh-CN"
        assert result.error_type == "custom_endpoint_unreachable"
        assert "Ollama" in result.user_message
        assert "无法连接" in result.user_message
        assert len(result.resolution_steps) > 0
        assert all(isinstance(step, str) for step in result.resolution_steps)

    def test_locale_auto_detection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test automatic locale detection from environment."""
        monkeypatch.setenv("MYRM_LOCALE", "zh-CN")

        exc = ValueError("Model 'llama3.2' not found")
        context = ErrorContext(model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:11434")

        result = LLMErrorDiagnostic.diagnose(exc, context)

        assert result.locale == "zh-CN"
        assert "未找到" in result.user_message or "模型" in result.user_message

    def test_fallback_to_english(self) -> None:
        """Test fallback to English for unsupported locale."""
        exc = ConnectionError("Connection refused")

        # Request unsupported locale (should fallback to en)
        result = LLMErrorDiagnostic.diagnose(exc, locale="fr")

        assert result.locale == "fr"  # Requested locale preserved
        assert "Unable to connect" in result.user_message  # English fallback

    def test_model_not_found_with_params(self) -> None:
        """Test model not found error with template parameters."""
        exc = ValueError("Model 'gpt-4' not found")
        context = ErrorContext(model_name="gpt-4", is_custom_endpoint=False)

        result_en = LLMErrorDiagnostic.diagnose(exc, context, locale="en")
        result_zh = LLMErrorDiagnostic.diagnose(exc, context, locale="zh-CN")

        assert "gpt-4" in result_en.user_message
        assert "gpt-4" in result_zh.user_message
        assert "not found" in result_en.user_message.lower()
        assert "未找到" in result_zh.user_message

    def test_rate_limit_error_translation(self) -> None:
        """Test rate limit error translation."""
        exc = Exception("Rate limit exceeded")

        result_en = LLMErrorDiagnostic.diagnose(exc, locale="en")
        result_zh = LLMErrorDiagnostic.diagnose(exc, locale="zh-CN")

        assert result_en.error_type == "rate_limit"
        assert result_zh.error_type == "rate_limit"
        assert "rate limit" in result_en.user_message.lower()
        assert "速率限制" in result_zh.user_message

    def test_context_overflow_error_translation(self) -> None:
        """Test context overflow error translation."""
        exc = Exception("Context length exceeds model limit")

        result_en = LLMErrorDiagnostic.diagnose(exc, locale="en")
        result_zh = LLMErrorDiagnostic.diagnose(exc, locale="zh-CN")

        assert result_en.error_type == "context_overflow"
        assert result_zh.error_type == "context_overflow"
        assert "context" in result_en.user_message.lower()
        assert "上下文" in result_zh.user_message

    def test_unknown_error_with_message(self) -> None:
        """Test unknown error with error message parameter."""
        exc = Exception("Some random error")

        result_en = LLMErrorDiagnostic.diagnose(exc, locale="en")
        result_zh = LLMErrorDiagnostic.diagnose(exc, locale="zh-CN")

        assert result_en.error_type == "unknown"
        assert result_zh.error_type == "unknown"
        assert "Some random error" in result_en.user_message
        assert "Some random error" in result_zh.user_message

    def test_missing_template_parameter_graceful_fallback(self) -> None:
        """Test that missing template parameters are handled gracefully."""
        from myrm_agent_harness.agent.errors.diagnostics.i18n import get_locale_manager

        manager = get_locale_manager()
        # Register a translation with missing parameter
        manager.register_translations(
            "test",
            {
                "connection": {
                    "user_message": "Error: {missing_param}",
                    "resolution_steps": ["Step with {missing_param}"],
                }
            },
        )

        # Should not raise KeyError, should use empty string for missing params
        result = manager.translate("connection", "user_message", "test")
        assert isinstance(result, str)
        assert "Error: " in result  # Should have partial message

        result_steps = manager.translate("connection", "resolution_steps", "test")
        assert isinstance(result_steps, list)
        assert len(result_steps) == 1
        assert "Step with " in result_steps[0]

    def test_unsupported_locale_fallback_to_english(self) -> None:
        """Test that unsupported locales fall back to English."""
        exc = ConnectionError("Connection refused")

        # Request unsupported locale (should fallback to en)
        result = LLMErrorDiagnostic.diagnose(exc, locale="fr")

        assert result.locale == "fr"  # Requested locale preserved
        assert "Unable to connect" in result.user_message  # English fallback content

    def test_locale_normalization(self) -> None:
        """Test locale string normalization."""
        from myrm_agent_harness.agent.errors.diagnostics.i18n import get_locale_manager

        manager = get_locale_manager()

        # Test various formats
        assert manager._normalize_locale("zh_CN.UTF-8") == "zh-CN"
        assert manager._normalize_locale("zh_CN") == "zh-CN"
        assert manager._normalize_locale("zh") == "zh-CN"
        assert manager._normalize_locale("ja") == "ja"
        assert manager._normalize_locale("ko") == "ko"
        assert manager._normalize_locale("de") == "de"
        assert manager._normalize_locale("fr") == "fr"
        assert manager._normalize_locale("pt") == "pt-BR"

    def test_register_custom_translations(self) -> None:
        """Test registering custom translations for new locale."""
        from myrm_agent_harness.agent.errors.diagnostics.i18n import get_locale_manager

        manager = get_locale_manager()

        # Register Japanese translations
        manager.register_translations(
            "ja",
            {
                "connection": {
                    "user_message": "LLMエンドポイントに接続できません",
                    "resolution_steps": ["サービスが起動しているか確認してください"],
                }
            },
        )

        # Should be able to retrieve Japanese translation
        result = manager.translate("connection", "user_message", "ja")
        assert result == "LLMエンドポイントに接続できません"

        result_steps = manager.translate("connection", "resolution_steps", "ja")
        assert result_steps == ["サービスが起動しているか確認してください"]

    def test_connection_error_generic(self) -> None:
        """Test generic connection error translation."""
        exc = ConnectionError("Connection refused")
        # No context = generic connection error

        result_en = LLMErrorDiagnostic.diagnose(exc, locale="en")
        result_zh = LLMErrorDiagnostic.diagnose(exc, locale="zh-CN")

        assert result_en.error_type == "connection"
        assert result_zh.error_type == "connection"
        assert "Unable to connect" in result_en.user_message
        assert "无法连接" in result_zh.user_message

    def test_api_key_error_translation(self) -> None:
        """Test API key error translation."""
        exc = Exception("Invalid API key")

        result_en = LLMErrorDiagnostic.diagnose(exc, locale="en")
        result_zh = LLMErrorDiagnostic.diagnose(exc, locale="zh-CN")

        assert result_en.error_type == "api_key"
        assert result_zh.error_type == "api_key"
        assert "API key authentication failed" in result_en.user_message
        assert "API 密钥认证失败" in result_zh.user_message

    def test_timeout_error_chinese_translation(self) -> None:
        """Test timeout error Chinese translation."""
        exc = Exception("Request timed out")

        result = LLMErrorDiagnostic.diagnose(exc, locale="zh-CN")

        assert result.error_type == "timeout"
        assert "超时" in result.user_message
        assert len(result.resolution_steps) > 0

    def test_service_name_inference(self) -> None:
        """Test service name inference for different endpoints."""
        exc = ConnectionError("Connection refused")

        # Test Ollama (port 11434)
        context_ollama = ErrorContext(model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:11434")
        result = LLMErrorDiagnostic.diagnose(exc, context_ollama, locale="en")
        assert "Ollama" in result.user_message

        # Test LM Studio (port 1234)
        context_lm_studio = ErrorContext(
            model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:1234"
        )
        result = LLMErrorDiagnostic.diagnose(exc, context_lm_studio, locale="en")
        assert "LM Studio" in result.user_message

        # Test vLLM
        context_vllm = ErrorContext(
            model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:8000/vllm"
        )
        result = LLMErrorDiagnostic.diagnose(exc, context_vllm, locale="en")
        assert "vLLM" in result.user_message

        # Test custom service
        context_custom = ErrorContext(
            model_name="llama3.2", is_custom_endpoint=True, base_url="http://custom-llm.example.com"
        )
        result = LLMErrorDiagnostic.diagnose(exc, context_custom, locale="en")
        assert "custom LLM service" in result.user_message

    def test_port_extraction(self) -> None:
        """Test port number extraction from URLs."""
        exc = ConnectionError("Connection refused")

        context_with_port = ErrorContext(
            model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:11434"
        )
        result = LLMErrorDiagnostic.diagnose(exc, context_with_port, locale="en")
        assert "11434" in str(result.resolution_steps)

        # Test URL without port
        context_no_port = ErrorContext(model_name="llama3.2", is_custom_endpoint=True, base_url="http://example.com")
        result = LLMErrorDiagnostic.diagnose(exc, context_no_port, locale="en")
        # Should handle gracefully (use "unknown" as port)

    def test_model_name_extraction_from_error(self) -> None:
        """Test model name extraction from error messages."""
        # Test with model name in error message
        exc1 = ValueError("Model: llama3.2 not found")
        result1 = LLMErrorDiagnostic.diagnose(exc1, locale="en")
        assert "llama3.2" in result1.user_message

        # Test with model name from context (error message contains 'not found' but not model name)
        exc2 = ValueError("The requested model not found")
        context = ErrorContext(model_name="gpt-4-turbo", is_custom_endpoint=False)
        result2 = LLMErrorDiagnostic.diagnose(exc2, context, locale="en")
        assert "gpt-4-turbo" in result2.user_message

    def test_locale_detection_fallback_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test locale detection fallback chain."""
        from myrm_agent_harness.agent.errors.diagnostics.i18n import LocaleManager

        # Clear all locale env vars
        monkeypatch.delenv("MYRM_LOCALE", raising=False)
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_MESSAGES", raising=False)
        monkeypatch.delenv("LANG", raising=False)

        manager = LocaleManager(default_locale="en")

        # Should fallback to default_locale
        detected = manager.detect_locale()
        assert detected == "en"

        # Test MYRM_LOCALE (highest priority)
        monkeypatch.setenv("MYRM_LOCALE", "zh-CN")
        detected = manager.detect_locale()
        assert detected == "zh-CN"

        # Test LC_ALL (second priority)
        monkeypatch.delenv("MYRM_LOCALE")
        monkeypatch.setenv("LC_ALL", "ja")
        detected = manager.detect_locale()
        assert detected == "ja"

    def test_safe_format_multiple_missing_params(self) -> None:
        """Test safe format with multiple missing parameters."""
        from myrm_agent_harness.agent.errors.diagnostics.i18n import get_locale_manager

        manager = get_locale_manager()
        manager.register_translations(
            "test-multi",
            {
                "connection": {
                    "user_message": "{param1} {param2} {param3}",
                    "resolution_steps": ["{param1}", "{param2}"],
                }
            },
        )

        # Should not raise KeyError, should use empty string for all missing params
        result = manager.translate("connection", "user_message", "test-multi")
        assert isinstance(result, str)
        # Should have spaces but empty params
        assert result == "  "

    def test_translation_completeness_validation_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that translation completeness validation logs warnings for missing translations."""
        from myrm_agent_harness.agent.errors.diagnostics.i18n import LocaleManager

        # Create a manager with incomplete translations
        manager = LocaleManager()
        manager._translations["incomplete"] = {
            "connection": {
                "user_message": "Connection error",
                # Missing resolution_steps
            },
            # Missing other error types
        }

        with caplog.at_level("WARNING"):
            manager._validate_translations()

        # Should log warnings for missing translations
        assert any("Missing" in record.message for record in caplog.records)

    def test_japanese_translation(self) -> None:
        """Test Japanese (ja) error translation."""
        from myrm_agent_harness.agent.errors.diagnostics import ErrorContext, LLMErrorDiagnostic

        context = ErrorContext(model_name="gpt-4", is_custom_endpoint=False)
        error = Exception("invalid api key")

        result = LLMErrorDiagnostic.diagnose(error, context, locale="ja")

        assert result.locale == "ja"
        assert result.error_type == "api_key"
        assert "API" in result.user_message or "キー" in result.user_message
        assert len(result.resolution_steps) > 0

    def test_korean_translation(self) -> None:
        """Test Korean (ko) error translation."""
        from myrm_agent_harness.agent.errors.diagnostics import ErrorContext, LLMErrorDiagnostic

        context = ErrorContext(model_name="claude-3", is_custom_endpoint=False)
        error = Exception("Rate limit exceeded")

        result = LLMErrorDiagnostic.diagnose(error, context, locale="ko")

        assert result.locale == "ko"
        assert "속도" in result.user_message or "제한" in result.user_message
        assert len(result.resolution_steps) > 0

    def test_german_translation(self) -> None:
        """Test German (de) error translation."""
        from myrm_agent_harness.agent.errors.diagnostics import ErrorContext, LLMErrorDiagnostic

        context = ErrorContext(model_name="gpt-4", is_custom_endpoint=False)
        error = Exception("Connection refused")

        result = LLMErrorDiagnostic.diagnose(error, context, locale="de")

        assert result.locale == "de"
        assert "Verbindung" in result.user_message or "fehlgeschlagen" in result.user_message.lower()
        assert len(result.resolution_steps) > 0
