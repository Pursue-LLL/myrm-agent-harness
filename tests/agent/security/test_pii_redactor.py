"""Tests for pii_redactor — PII masking and redaction."""

import pytest

from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii, redact_value
from myrm_agent_harness.core.security.detection.custom_rules import CustomRules


class TestRedactPii:
    def test_empty_content(self) -> None:
        text, count = redact_pii("")
        assert text == ""
        assert count == 0

    def test_no_pii(self) -> None:
        text, count = redact_pii("This is a normal message with no sensitive data.")
        assert count == 0
        assert text == "This is a normal message with no sensitive data."

    def test_china_phone_redacted(self) -> None:
        text, count = redact_pii("联系人 13812345678 请回电")
        assert count >= 1
        assert "138****5678" in text
        assert "[PII:phone]" in text
        assert "13812345678" not in text

    def test_email_redacted(self) -> None:
        text, count = redact_pii("邮箱 zhangsan@company.com 联系")
        assert count >= 1
        assert "[PII:email]" in text
        assert "zhangsan" not in text
        assert "@company.com" in text  # domain preserved

    def test_china_id_valid_redacted(self) -> None:
        text, count = redact_pii("身份证 110101199003074530 存档")
        assert count >= 1
        assert "[PII:id_card]" in text
        assert "110101" in text  # prefix preserved
        assert "4530" in text  # suffix preserved
        assert "110101199003074530" not in text

    def test_china_id_invalid_not_redacted(self) -> None:
        text, _count = redact_pii("number 110101199003074531")
        # Invalid checksum — should not be redacted
        assert "110101199003074531" in text

    def test_bank_card_valid_redacted(self) -> None:
        text, count = redact_pii("银行卡 4532015112830366 转账")
        assert count >= 1
        assert "[PII:bank_card]" in text
        assert "0366" in text  # last 4 preserved
        assert "4532015112830366" not in text

    def test_password_redacted(self) -> None:
        text, count = redact_pii("password=MySuperSecret123!")
        assert count >= 1
        assert "[PII:password]" in text
        assert "MySuperSecret123!" not in text

    def test_us_ssn_redacted(self) -> None:
        text, count = redact_pii("SSN: 123-45-6789")
        assert count >= 1
        assert "[PII:ssn]" in text
        assert "***-**-6789" in text
        assert "123-45-6789" not in text

    def test_private_ip_redacted(self) -> None:
        text, count = redact_pii("connect 192.168.1.100 via SSH")
        assert count >= 1
        assert "[PII:private_ip]" in text
        assert "192.168" in text  # prefix preserved

    def test_multiple_pii_types(self) -> None:
        text, count = redact_pii("电话 13812345678 邮箱 user@real.com")
        assert count >= 2
        assert "[PII:phone]" in text
        assert "[PII:email]" in text

    def test_placeholder_email_still_redacted(self) -> None:
        # Redactor doesn't skip placeholders for S2 patterns (only for S3)
        text, count = redact_pii("email: user@example.com contact us")
        assert count >= 1
        assert "[PII:email]" in text

    def test_china_passport_redacted(self) -> None:
        text, count = redact_pii("护照号 E12345678 出境")
        assert count >= 1
        assert "[PII:passport]" in text

    def test_china_address_redacted(self) -> None:
        text, count = redact_pii("地址是北京市朝阳区三里屯路12号")
        assert count >= 1
        assert "[PII:address]" in text

    def test_credit_card_visible_redacted(self) -> None:
        # The grouped number fails the Luhn check, so only the looser visible-card rule applies.
        text, count = redact_pii("card 4532-0151-1283-0367")
        assert count >= 1
        assert "[PII:credit_card]" in text
        assert "0367" in text  # last 4 preserved


class TestRedactingRedactedText:
    """Text that was redacted once passes through the redactor again unchanged: the guard rescans state on every call."""

    @pytest.mark.parametrize(
        "text",
        [
            "call 13812345678 please",
            "mail alice@example.com now",
            "id 110101199003074530 ok",
            "card 4532015112830366 x",
            "password: hunter2secret ok",
            'pwd = "S3cr3tP4ss!" ok',
            "passport E12345678 ok",
            "tel +1 415 555 2671 ok",
            "host 192.168.1.20 ok",
            "地址是北京市朝阳区三里屯路12号",
            "ssn 123-45-6789 ok",
            "API_KEY=abcdef1234567890abcdef1234567890 ok",
            "Phone 13812345678, password: hunter2secret, a@b.com",
            "password: 123456 is my router login",
            "密码：888888 谢谢",
            "我的密码是 Zk9%mango42 帮我登录",
            'config = {"password":"abc12345","x":1}',
            "[PII:password] and other: Zk9%mango42x",
        ],
    )
    def test_a_second_pass_changes_nothing(self, text: str) -> None:
        once, _ = redact_pii(text)

        twice, count = redact_pii(once)

        assert twice == once
        assert count == 0


class TestRedactValue:
    def test_known_type_china_phone(self) -> None:
        result = redact_value("13812345678", "china_phone")
        assert "[PII:phone]" in result

    def test_known_type_email(self) -> None:
        result = redact_value("zhangsan@company.com", "email")
        assert "[PII:email]" in result

    def test_known_type_us_ssn(self) -> None:
        result = redact_value("123-45-6789", "us_ssn")
        assert "[PII:ssn]" in result

    def test_unknown_type_fallback(self) -> None:
        result = redact_value("some data", "unknown_type")
        assert "[PII:unknown_type]" in result


class TestRedactingPasswords:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ('password: "Zk9%mango42", next', 'password: "[REDACTED] [PII:password]", next'),
            ("password=password) # default", "password=password) # default"),
            ("password=${DB_PASS}", "password=${DB_PASS}"),
            ('{"password":"abc12345","x":1}', '{"password":"[REDACTED] [PII:password]","x":1}'),
            ("我的密码是 Zk9%mango42 帮我登录", "我的密码是 [REDACTED] [PII:password] 帮我登录"),
            ("密码：888888 谢谢", "密码：[REDACTED] [PII:password] 谢谢"),
            ("DB_PASSWORD=hunter2xyz", "DB_PASSWORD=[REDACTED] [PII:password]"),
        ],
        ids=["quote-and-comma-kept", "label-itself", "template", "json", "cjk-sentence", "cjk-colon", "env-name"],
    )
    def test_only_the_value_is_replaced(self, text: str, expected: str) -> None:
        assert redact_pii(text)[0] == expected

    def test_a_password_wins_over_the_pattern_it_also_matches(self) -> None:
        text, count = redact_pii("password: 13812345678")

        assert text == "password: [REDACTED] [PII:password]"
        assert count == 1


class TestRedactingCustomRules:
    _KEYWORD = CustomRules(keywords=("凤凰计划",))

    def test_a_call_without_rules_knows_no_custom_term(self) -> None:
        assert redact_pii("帮我总结凤凰计划Q3预算") == ("帮我总结凤凰计划Q3预算", 0)

    def test_a_keyword_inside_a_sentence_is_replaced(self) -> None:
        text, count = redact_pii("帮我总结凤凰计划Q3预算超支原因", self._KEYWORD)

        assert text == "帮我总结[REDACTED] [PII:custom]Q3预算超支原因"
        assert count == 1

    def test_every_occurrence_is_replaced(self) -> None:
        text, count = redact_pii("凤凰计划的预算，凤凰计划的人员", self._KEYWORD)

        assert "凤凰计划" not in text
        assert count == 2

    def test_a_pattern_is_replaced(self) -> None:
        text, count = redact_pii("EMP-123456 is on leave", CustomRules(patterns=(r"EMP-\d{6}",)))

        assert text == "[REDACTED] [PII:custom] is on leave"
        assert count == 1

    def test_a_custom_term_and_built_in_pii_are_both_replaced(self) -> None:
        text, count = redact_pii("凤凰计划负责人电话 13812345678", self._KEYWORD)

        assert "凤凰计划" not in text
        assert "13812345678" not in text
        assert count == 2

    def test_a_keyword_inside_a_longer_ascii_word_is_left_alone(self) -> None:
        assert redact_pii("the spinners ran", CustomRules(keywords=("pin",))) == ("the spinners ran", 0)

    @pytest.mark.parametrize(
        "text",
        ["凤凰计划", "帮我总结凤凰计划Q3，凤凰计划二期", "凤凰计划 phone 13812345678 password: Zk9%mango42"],
        ids=["bare", "twice", "with-built-ins"],
    )
    def test_redacting_the_output_again_changes_nothing(self, text: str) -> None:
        once, _ = redact_pii(text, self._KEYWORD)

        assert redact_pii(once, self._KEYWORD) == (once, 0)

    def test_a_keyword_that_names_the_marker_cannot_rewrite_it(self) -> None:
        rules = CustomRules(keywords=("PII", "custom", "REDACTED"))
        once, _ = redact_pii("联系 13812345678", rules)

        assert redact_pii(once, rules) == (once, 0)
