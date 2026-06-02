"""Tests for pii_classifier — PII detection and classification."""

from myrm_agent_harness.agent.security.detection.pii_classifier import (
    _china_id_valid,
    _keyword_matches,
    _luhn_valid,
    classify_content,
    classify_tool_params,
    classify_tool_result,
)
from myrm_agent_harness.agent.security.types import PrivacyPolicy, SensitivityLevel

_ENABLED = PrivacyPolicy(enabled=True)
_DISABLED = PrivacyPolicy(enabled=False)


class TestFastPath:
    def test_disabled_policy_returns_s1(self):
        result = classify_content("sensitive phone 13812345678", _DISABLED)
        assert result.level == SensitivityLevel.S1

    def test_empty_content_returns_s1(self):
        assert classify_content("", _ENABLED).level == SensitivityLevel.S1

    def test_short_content_skips(self):
        assert classify_content("abc", _ENABLED).level == SensitivityLevel.S1


class TestS3Detection:
    """Confidential data detection — identity docs, financial, passwords."""

    def test_china_id_card_valid(self):
        # Valid checksum ID
        result = classify_content("身份证号码 110101199003074530", _ENABLED)
        assert result.level == SensitivityLevel.S3
        assert "china_id_card" in result.patterns

    def test_china_id_card_invalid_checksum_skipped(self):
        result = classify_content("number 110101199003074531", _ENABLED)
        assert result.level == SensitivityLevel.S1

    def test_bank_card_luhn_valid(self):
        # 6222021234567890018 passes Luhn
        result = classify_content("卡号 4532015112830366", _ENABLED)
        assert result.level == SensitivityLevel.S3
        assert "bank_card" in result.patterns

    def test_bank_card_invalid_luhn_skipped(self):
        result = classify_content("number 6222021234567890019", _ENABLED)
        assert result.level == SensitivityLevel.S1

    def test_password_context(self):
        result = classify_content("password=MySecret123!", _ENABLED)
        assert result.level == SensitivityLevel.S3
        assert "password_context" in result.patterns

    def test_china_passport(self):
        result = classify_content("护照 E12345678", _ENABLED)
        assert result.level == SensitivityLevel.S3
        assert "china_passport" in result.patterns


class TestS2Detection:
    """Sensitive data detection — contact info, location."""

    def test_china_phone(self):
        result = classify_content("我的手机号 13812345678", _ENABLED)
        assert result.level == SensitivityLevel.S2
        assert "china_phone" in result.patterns

    def test_china_phone_with_prefix(self):
        result = classify_content("call +86 13812345678", _ENABLED)
        assert result.level == SensitivityLevel.S2

    def test_email(self):
        result = classify_content("请联系 zhangsan@company.com", _ENABLED)
        assert result.level == SensitivityLevel.S2
        assert "email" in result.patterns

    def test_credit_card_visible_format(self):
        result = classify_content("card 4532-0151-1283-0366", _ENABLED)
        assert result.level == SensitivityLevel.S2
        assert "credit_card_visible" in result.patterns

    def test_private_ip(self):
        result = classify_content("connect to 192.168.1.100", _ENABLED)
        assert result.level == SensitivityLevel.S2
        assert "private_ip" in result.patterns

    def test_us_ssn(self):
        result = classify_content("SSN is 123-45-6789", _ENABLED)
        assert result.level == SensitivityLevel.S2
        assert "us_ssn" in result.patterns

    def test_intl_phone(self):
        result = classify_content("call +1-202-555-0123", _ENABLED)
        assert result.level == SensitivityLevel.S2
        assert "intl_phone" in result.patterns


class TestPlaceholderExclusion:
    def test_placeholder_email_skipped(self):
        result = classify_content("email: user@example.com", _ENABLED)
        assert result.level == SensitivityLevel.S1

    def test_placeholder_phone_skipped(self):
        result = classify_content("phone: 12345678901", _ENABLED)
        assert result.level == SensitivityLevel.S1

    def test_test_email_skipped(self):
        result = classify_content("test@test.com", _ENABLED)
        assert result.level == SensitivityLevel.S1


class TestCustomKeywords:
    def test_custom_s3_keyword(self):
        policy = PrivacyPolicy(enabled=True, custom_keywords_s3=("社保号码",))
        result = classify_content("请提供 社保号码 信息", policy)
        assert result.level == SensitivityLevel.S3
        assert any("custom_s3_keyword" in p for p in result.patterns)

    def test_custom_s2_keyword(self):
        policy = PrivacyPolicy(enabled=True, custom_keywords_s2=("微信号",))
        result = classify_content("请发 微信号 给我", policy)
        assert result.level == SensitivityLevel.S2

    def test_custom_s3_pattern(self):
        policy = PrivacyPolicy(enabled=True, custom_patterns_s3=(r"PROJ-\d{6}"))
        result = classify_content("project PROJ-123456", policy)
        assert result.level == SensitivityLevel.S3


class TestToolParams:
    def test_sensitive_tool_s3(self):
        policy = PrivacyPolicy(enabled=True, sensitive_tools_s3=("vault_read"))
        result = classify_tool_params("vault_read", {"key": "abc"}, policy)
        assert result.level == SensitivityLevel.S3

    def test_sensitive_path_env(self):
        result = classify_tool_params("read_file", {"path": "/home/user/.env"}, _ENABLED)
        assert result.level == SensitivityLevel.S3
        assert any("sensitive_file_ext" in p or "sensitive_path" in p for p in result.patterns)

    def test_sensitive_path_ssh_key(self):
        result = classify_tool_params("read_file", {"file": "/home/user/.ssh/id_rsa"}, _ENABLED)
        assert result.level == SensitivityLevel.S3

    def test_pii_in_param_value(self):
        result = classify_tool_params("send_email", {"body": "请联系 zhangsan@company.com"}, _ENABLED)
        assert result.level == SensitivityLevel.S2

    def test_disabled_returns_s1(self):
        result = classify_tool_params("vault_read", {"key": "abc"}, _DISABLED)
        assert result.level == SensitivityLevel.S1


class TestToolResult:
    def test_pii_in_result(self):
        result = classify_tool_result("用户手机号 13812345678", "read_file", _ENABLED)
        assert result.level == SensitivityLevel.S2

    def test_clean_result(self):
        result = classify_tool_result("Task completed successfully", "shell_exec", _ENABLED)
        assert result.level == SensitivityLevel.S1


class TestChinaIdValidation:
    def test_valid_id(self):
        assert _china_id_valid("110101199003074530") is True

    def test_invalid_checksum(self):
        assert _china_id_valid("110101199003074531") is False

    def test_short_id(self):
        assert _china_id_valid("1234567") is False


class TestLuhnValidation:
    def test_valid_card(self):
        assert _luhn_valid("4532015112830366") is True

    def test_invalid_card(self):
        assert _luhn_valid("4532015112830367") is False

    def test_too_short(self):
        assert _luhn_valid("12345") is False

    def test_non_digit(self):
        assert _luhn_valid("abc") is False


class TestKeywordMatching:
    def test_exact_match(self):
        assert _keyword_matches("my 社保号码 is here", "社保号码") is True

    def test_no_match(self):
        assert _keyword_matches("normal text", "社保号码") is False

    def test_file_extension(self):
        assert _keyword_matches("read config.env file", ".env") is True

    def test_partial_word_boundary(self):
        assert _keyword_matches("password123", "pass") is False


class TestS3ShortCircuit:
    """Verify that S3 detection short-circuits (doesn't continue to S2)."""

    def test_s3_with_s2_present(self):
        # Both S3 (password) and S2 (phone) present — should return S3
        content = "password=secret123 call 13812345678"
        result = classify_content(content, _ENABLED)
        assert result.level == SensitivityLevel.S3
