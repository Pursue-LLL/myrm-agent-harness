"""Tests for authentication failure detection"""

from myrm_agent_harness.observability.auth_detector import detect_auth_failure, get_auth_error_hint


class TestAuthDetector:
    """Test authentication failure detection"""

    def test_detect_openai_auth_failure(self):
        """Test detection of OpenAI auth failures"""
        exc = Exception("OpenAI API error: invalid_api_key")
        assert detect_auth_failure(exc) is True

    def test_detect_anthropic_auth_failure(self):
        """Test detection of Anthropic auth failures"""
        exc = Exception("Anthropic error: authentication_error")
        assert detect_auth_failure(exc) is True

    def test_detect_401_error(self):
        """Test detection of 401 HTTP errors"""
        exc = Exception("HTTP 401: Unauthorized")
        assert detect_auth_failure(exc) is True

    def test_detect_403_error(self):
        """Test detection of 403 HTTP errors"""
        exc = Exception("HTTP 403: Forbidden")
        assert detect_auth_failure(exc) is True

    def test_detect_generic_unauthorized(self):
        """Test detection of generic unauthorized errors"""
        exc = Exception("Request failed: unauthorized access")
        assert detect_auth_failure(exc) is True

    def test_no_detection_network_error(self):
        """Test that network errors are not detected as auth failures"""
        exc = Exception("Connection timeout")
        assert detect_auth_failure(exc) is False

    def test_no_detection_rate_limit(self):
        """Test that rate limit errors are not detected as auth failures"""
        exc = Exception("Rate limit exceeded")
        assert detect_auth_failure(exc) is False

    def test_no_detection_generic_error(self):
        """Test that generic errors are not detected as auth failures"""
        exc = Exception("Something went wrong")
        assert detect_auth_failure(exc) is False

    def test_case_insensitive_detection(self):
        """Test that detection is case-insensitive"""
        exc = Exception("AUTHENTICATION ERROR: INVALID API KEY")
        assert detect_auth_failure(exc) is True


class TestAuthErrorHint:
    """Test auth error hint generation"""

    def test_openai_hint(self):
        """Test OpenAI-specific hint"""
        exc = Exception("OpenAI API error: invalid_api_key")
        hint = get_auth_error_hint(exc)
        assert "OpenAI" in hint
        assert "OPENAI_API_KEY" in hint

    def test_anthropic_hint(self):
        """Test Anthropic-specific hint"""
        exc = Exception("Anthropic error: authentication_error")
        hint = get_auth_error_hint(exc)
        assert "Anthropic" in hint
        assert "ANTHROPIC_API_KEY" in hint

    def test_google_hint(self):
        """Test Google/Gemini-specific hint"""
        exc = Exception("Google API error: unauthenticated")
        hint = get_auth_error_hint(exc)
        assert "Google" in hint or "Gemini" in hint
        assert "GOOGLE_API_KEY" in hint

    def test_generic_hint(self):
        """Test generic hint for unknown providers"""
        exc = Exception("Authentication failed: 401")
        hint = get_auth_error_hint(exc)
        assert "LLM API authentication failed" in hint
        assert "API keys" in hint
