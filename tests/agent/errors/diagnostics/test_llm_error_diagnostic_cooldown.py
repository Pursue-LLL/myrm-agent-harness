"""Test cooldown hint generation in LLMErrorDiagnostic."""

from myrm_agent_harness.agent.errors.diagnostics import ErrorContext, LLMErrorDiagnostic


class TestCooldownHint:
    """Test cooldown_remaining_ms hint in diagnostic messages."""

    def test_rate_limit_with_cooldown_en(self):
        """Test rate limit error with cooldown hint (English)."""
        exc = Exception("rate limit exceeded")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="en", cooldown_remaining_ms=30000)

        assert diagnostic.error_type == "rate_limit"
        assert diagnostic.locale == "en"
        assert "Retry after 30 seconds" in diagnostic.user_message
        assert diagnostic.user_message.startswith("API rate limit exceeded")

    def test_rate_limit_with_cooldown_zh_cn(self):
        """Test rate limit error with cooldown hint (Chinese)."""
        exc = Exception("too many requests")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="zh-CN", cooldown_remaining_ms=60000)

        assert diagnostic.error_type == "rate_limit"
        assert diagnostic.locale == "zh-CN"
        assert "请等待60秒后重试" in diagnostic.user_message

    def test_rate_limit_without_cooldown(self):
        """Test rate limit error without cooldown (no hint)."""
        exc = Exception("429 too many requests")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="en")

        assert diagnostic.error_type == "rate_limit"
        assert "Retry after" not in diagnostic.user_message
        assert diagnostic.user_message == "API rate limit exceeded"

    def test_cooldown_single_second_en(self):
        """Test singular form: 1 second (English)."""
        exc = Exception("rate limit")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="en", cooldown_remaining_ms=1000)

        assert "Retry after 1 second" in diagnostic.user_message
        assert "seconds" not in diagnostic.user_message or "1 second." in diagnostic.user_message

    def test_cooldown_plural_seconds_en(self):
        """Test plural form: multiple seconds (English)."""
        exc = Exception("rate limit")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="en", cooldown_remaining_ms=120000)

        assert "Retry after 120 seconds" in diagnostic.user_message

    def test_cooldown_japanese(self):
        """Test cooldown hint in Japanese."""
        exc = Exception("too many requests")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="ja", cooldown_remaining_ms=45000)

        assert diagnostic.locale == "ja"
        assert "45秒後に再試行してください" in diagnostic.user_message

    def test_cooldown_korean(self):
        """Test cooldown hint in Korean."""
        exc = Exception("rate limit exceeded")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="ko", cooldown_remaining_ms=90000)

        assert diagnostic.locale == "ko"
        assert "90초 후에 다시 시도하세요" in diagnostic.user_message

    def test_cooldown_german(self):
        """Test cooldown hint in German."""
        exc = Exception("429 too many requests")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="de", cooldown_remaining_ms=75000)

        assert diagnostic.locale == "de"
        assert "75 Sekunden erneut" in diagnostic.user_message

    def test_cooldown_zero_milliseconds(self):
        """Test cooldown_remaining_ms=0 (no hint)."""
        exc = Exception("rate limit")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="en", cooldown_remaining_ms=0)

        assert "Retry after" not in diagnostic.user_message

    def test_cooldown_negative_milliseconds(self):
        """Test negative cooldown (no hint)."""
        exc = Exception("rate limit")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, locale="en", cooldown_remaining_ms=-1000)

        assert "Retry after" not in diagnostic.user_message

    def test_cooldown_with_all_error_types(self):
        """Test cooldown hint works with all error types."""
        test_cases = [
            ("connection refused", "connection", "en", 30000, "30 seconds"),
            ("invalid api key", "api_key", "zh-CN", 45000, "45秒"),
            ("model not found", "model", "ja", 60000, "60秒"),
            ("context length exceeded", "context_overflow", "ko", 90000, "90초"),
            ("timeout", "timeout", "de", 120000, "120 Sekunden"),
        ]

        for error_msg, expected_type, locale, cooldown_ms, expected_hint_fragment in test_cases:
            exc = Exception(error_msg)
            diagnostic = LLMErrorDiagnostic.diagnose(exc, locale=locale, cooldown_remaining_ms=cooldown_ms)

            assert diagnostic.error_type == expected_type
            assert expected_hint_fragment in diagnostic.user_message

    def test_cooldown_with_custom_endpoint(self):
        """Test cooldown hint with custom endpoint error."""
        exc = Exception("connection refused")
        context = ErrorContext(model_name="llama3.2", is_custom_endpoint=True, base_url="http://localhost:11434")

        diagnostic = LLMErrorDiagnostic.diagnose(exc, context, locale="en", cooldown_remaining_ms=15000)

        assert diagnostic.error_type == "custom_endpoint_unreachable"
        assert "Ollama" in diagnostic.user_message
        assert "Retry after 15 seconds" in diagnostic.user_message


class TestCooldownDuration:
    """Long provider-stated waits read as minutes / hours / days, rounded up, in every locale."""

    @staticmethod
    def _hint(ms: int, locale: str) -> str:
        return LLMErrorDiagnostic.diagnose(
            Exception("rate limit"), locale=locale, cooldown_remaining_ms=ms
        ).user_message

    def test_just_over_two_minutes_becomes_minutes_rounded_up(self):
        assert "Retry after 3 minutes." in self._hint(121_000, "en")

    def test_exactly_one_hour(self):
        assert "Retry after 1 hour." in self._hint(3_600_000, "en")

    def test_hours_and_minutes(self):
        assert "Retry after 3 hours 12 minutes." in self._hint((3 * 3600 + 12 * 60) * 1000, "en")

    def test_whole_hours_omit_the_minutes(self):
        assert "Retry after 5 hours." in self._hint(5 * 3600 * 1000, "en")

    def test_two_days_or_more_are_counted_in_days(self):
        assert "Retry after 3 days." in self._hint((2 * 86_400 + 60) * 1000, "en")
        assert "Retry after 2 days." in self._hint(48 * 3600 * 1000, "en")

    def test_a_partial_second_rounds_up(self):
        assert "Retry after 2 seconds." in self._hint(1_100, "en")

    def test_every_locale_localizes_hours_and_minutes(self):
        ms = (5 * 3600 + 30 * 60) * 1000
        assert "请等待5小时30分钟后重试" in self._hint(ms, "zh-CN")
        assert "5時間30分後に再試行してください" in self._hint(ms, "ja")
        assert "5시간 30분 후에 다시 시도하세요" in self._hint(ms, "ko")
        assert "in 5 Stunden 30 Minuten erneut" in self._hint(ms, "de")

    def test_german_plural_forms(self):
        assert "in 1 Stunde erneut" in self._hint(3_600_000, "de")
        assert "in 3 Tagen" not in self._hint(3 * 86_400_000, "de")
        assert "in 3 Tage erneut" in self._hint(3 * 86_400_000, "de")

    def test_unknown_locale_falls_back_to_english(self):
        assert "Retry after 2 hours." in self._hint(2 * 3600 * 1000, "fr")

    def test_hint_is_appended_for_every_diagnosis_exactly_once(self):
        result = LLMErrorDiagnostic.diagnose(Exception("connection refused"), locale="en", cooldown_remaining_ms=30_000)

        assert result.user_message.count("Retry after") == 1
