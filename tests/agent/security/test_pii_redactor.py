"""Tests for pii_redactor — PII masking and redaction."""

from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii, redact_value


class TestRedactPii:
    def test_empty_content(self):
        text, count = redact_pii("")
        assert text == ""
        assert count == 0

    def test_no_pii(self):
        text, count = redact_pii("This is a normal message with no sensitive data.")
        assert count == 0
        assert text == "This is a normal message with no sensitive data."

    def test_china_phone_redacted(self):
        text, count = redact_pii("联系人 13812345678 请回电")
        assert count >= 1
        assert "138****5678" in text
        assert "[PII:phone]" in text
        assert "13812345678" not in text

    def test_email_redacted(self):
        text, count = redact_pii("邮箱 zhangsan@company.com 联系")
        assert count >= 1
        assert "[PII:email]" in text
        assert "zhangsan" not in text
        assert "@company.com" in text  # domain preserved

    def test_china_id_valid_redacted(self):
        text, count = redact_pii("身份证 110101199003074530 存档")
        assert count >= 1
        assert "[PII:id_card]" in text
        assert "110101" in text  # prefix preserved
        assert "4530" in text  # suffix preserved
        assert "110101199003074530" not in text

    def test_china_id_invalid_not_redacted(self):
        text, _count = redact_pii("number 110101199003074531")
        # Invalid checksum — should not be redacted
        assert "110101199003074531" in text

    def test_bank_card_valid_redacted(self):
        text, count = redact_pii("银行卡 4532015112830366 转账")
        assert count >= 1
        assert "[PII:bank_card]" in text
        assert "0366" in text  # last 4 preserved
        assert "4532015112830366" not in text

    def test_password_redacted(self):
        text, count = redact_pii("password=MySuperSecret123!")
        assert count >= 1
        assert "[PII:password]" in text
        assert "MySuperSecret123!" not in text

    def test_us_ssn_redacted(self):
        text, count = redact_pii("SSN: 123-45-6789")
        assert count >= 1
        assert "[PII:ssn]" in text
        assert "***-**-6789" in text
        assert "123-45-6789" not in text

    def test_private_ip_redacted(self):
        text, count = redact_pii("connect 192.168.1.100 via SSH")
        assert count >= 1
        assert "[PII:private_ip]" in text
        assert "192.168" in text  # prefix preserved

    def test_multiple_pii_types(self):
        text, count = redact_pii("电话 13812345678 邮箱 user@real.com")
        assert count >= 2
        assert "[PII:phone]" in text
        assert "[PII:email]" in text

    def test_placeholder_email_still_redacted(self):
        # Redactor doesn't skip placeholders for S2 patterns (only for S3)
        text, count = redact_pii("email: user@example.com contact us")
        assert count >= 1
        assert "[PII:email]" in text

    def test_china_passport_redacted(self):
        text, count = redact_pii("护照号 E12345678 出境")
        assert count >= 1
        assert "[PII:passport]" in text

    def test_china_address_redacted(self):
        text, count = redact_pii("地址是北京市朝阳区三里屯路12号")
        assert count >= 1
        assert "[PII:address]" in text

    def test_credit_card_visible_redacted(self):
        text, count = redact_pii("card 4532-0151-1283-0366")
        assert count >= 1
        assert "[PII:credit_card]" in text
        assert "0366" in text  # last 4 preserved


class TestRedactValue:
    def test_known_type_china_phone(self):
        result = redact_value("13812345678", "china_phone")
        assert "[PII:phone]" in result

    def test_known_type_email(self):
        result = redact_value("zhangsan@company.com", "email")
        assert "[PII:email]" in result

    def test_known_type_us_ssn(self):
        result = redact_value("123-45-6789", "us_ssn")
        assert "[PII:ssn]" in result

    def test_unknown_type_fallback(self):
        result = redact_value("some data", "unknown_type")
        assert "[PII:unknown_type]" in result
