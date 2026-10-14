"""[POS]: tests/toolkits/memory/test_pii_gateway.py
[INPUT]: Statements a user might ask the memory to keep: cards, IBANs, IDs, secrets, passwords and ordinary facts.
[OUTPUT]: Assertions that the storage gate refuses what the privacy pipeline masks, refuses what it was already
refusing, and masks only the characters that are sensitive.
"""

import pytest

from myrm_agent_harness.agent.security.detection.pii_classifier import classify_content
from myrm_agent_harness.agent.security.types import PrivacyPolicy, SensitivityLevel
from myrm_agent_harness.toolkits.memory.noise_free_extractor import PIISafetyGateway

_GATE = PIISafetyGateway()
_MASKING_GATE = PIISafetyGateway(mask_instead_of_reject=True)


def _rules(statement: str) -> list[str]:
    return [violation.rule_name for violation in _GATE.inspect(statement).violations]


# Numbers that payment providers publish in their documentation.
_PUBLISHED_CARDS = (
    "4111111111111111",
    "4012888888881881",
    "5105105105105100",
    "2223000048400011",
    "371449635398431",
    "378734493671000",
    "6011000990139424",
    "3530111333300000",
    "6212345678901232",
)
# Networks the prefix table does not know: refused on the Luhn check alone.
_UNLISTED_NETWORK_CARDS = ("6759649826438453", "5018000000000009", "2200000000000053")
# Thirteen, fourteen and nineteen digits: refused when a keyword introduces them.
_UNUSUAL_LENGTH_CARDS = ("4222222222222", "30569309025904", "6759000000000000001")


class TestCards:
    @pytest.mark.parametrize("number", _PUBLISHED_CARDS + _UNLISTED_NETWORK_CARDS)
    def test_a_bare_card_number_is_refused_whatever_its_network(self, number: str) -> None:
        assert _rules(f"my number is {number} thanks") == ["credit_card"]

    @pytest.mark.parametrize(
        "typed",
        ["4111 1111 1111 1111", "4111-1111-1111-1111", "3782 822463 10005", "6222 0210 1001 1624 507"],
    )
    def test_a_card_typed_in_groups_is_refused(self, typed: str) -> None:
        assert _rules(f"卡 {typed} 请保存") == ["credit_card"]

    @pytest.mark.parametrize("number", _UNUSUAL_LENGTH_CARDS)
    def test_a_card_of_an_unusual_length_is_refused_when_a_keyword_introduces_it(self, number: str) -> None:
        assert _rules(f"card number {number} thanks") == ["credit_card"]

    @pytest.mark.parametrize("introduction", ["银行卡号：", "信用卡号是 ", "bank card (Maestro): "])
    def test_a_card_with_a_typo_is_refused_when_a_keyword_introduces_it(self, introduction: str) -> None:
        assert _rules(f"{introduction}4532015112830367 请记住") == ["credit_card"]

    @pytest.mark.parametrize(
        "statement",
        [
            "order 1234567890123456 shipped",
            "timestamp 1760254500000 in ms",
            "ref 4532015112830367 was rejected",
            "tracking 4111 1111 1111 1112",
        ],
    )
    def test_digits_that_fail_the_check_or_have_another_length_are_not_a_card(self, statement: str) -> None:
        assert _GATE.inspect(statement).is_clean

    def test_a_card_beside_an_iban_is_still_a_card(self) -> None:
        assert _rules("pay DE89 3704 0044 0532 0130 00 or card 4111 1111 1111 1111") == ["iban", "credit_card"]

    @pytest.mark.parametrize("iban", ["DE79 5156 6979 6156 7959 65", "AT480642482960179677"])
    def test_a_run_of_digits_inside_an_iban_is_not_read_as_a_card(self, iban: str) -> None:
        assert _rules(f"account {iban}") == ["iban"]


class TestIbans:
    @pytest.mark.parametrize(
        "iban",
        [
            "DE89370400440532013000",
            "DE89 3704 0044 0532 0130 00",
            "de89 3704 0044 0532 0130 00",
            "GB82 WEST 1234 5698 7654 32",
            "FR14 2004 1010 0505 0001 3M02 606",
            "NL91ABNA0417164300",
        ],
    )
    def test_an_iban_is_refused_however_it_is_typed(self, iban: str) -> None:
        assert _rules(f"汇款至 {iban} 请确认") == ["iban"]

    def test_an_iban_with_a_mistyped_check_digit_is_still_refused(self) -> None:
        assert _rules("pay to DE89 3704 0044 0532 0130 01 please") == ["iban"]

    @pytest.mark.parametrize("token", ["SF1234567890123", "JD0012345678901234", "ID20261014001"])
    def test_a_courier_or_order_number_is_not_an_iban(self, token: str) -> None:
        assert _GATE.inspect(f"tracking {token} delivered").is_clean


class TestIdentityNumbers:
    @pytest.mark.parametrize("number", ["11010519491231002X", "110101199003074537"])
    def test_a_national_id_is_refused(self, number: str) -> None:
        assert _rules(f"身份证 {number} 已登记") == ["national_id_cn"]

    def test_an_id_with_a_mistyped_check_digit_is_still_refused(self) -> None:
        assert _rules("身份证 110101199003074531 已登记") == ["national_id_cn"]

    def test_a_social_security_number_is_refused(self) -> None:
        assert _rules("ssn 123-45-6789 on file") == ["ssn_us"]


class TestSecrets:
    @pytest.mark.parametrize(
        "secret",
        [
            "sk-abcdef1234567890abcdef1234567890",
            "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdef",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUV",
            "xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx",
            "AKIAABCDEFGHIJKLMNOP",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            "bearer abcdefghijklmnopqrstuvwxyz0123456789ABC",
        ],
    )
    def test_a_credential_is_refused_once_and_its_middle_is_masked(self, secret: str) -> None:
        refused = _GATE.inspect(f"测试密钥 {secret} 存储")
        masked = _MASKING_GATE.inspect(f"测试密钥 {secret} 存储")

        assert [v.rule_name for v in refused.violations] == ["secret_token_key"]
        assert refused.violations[0].snippet_masked == "***"
        assert secret not in masked.sanitized_text
        assert "[REDACTED:" in masked.sanitized_text

    def test_a_private_key_block_is_refused(self) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA7bq98Kd1QdYvP\n-----END RSA PRIVATE KEY-----"

        assert "secret_token_key" in _rules(f"key:\n{pem}")


class TestPasswords:
    @pytest.mark.parametrize(
        "statement",
        [
            "my password is hunter22abc for the vpn",
            "我的密码是 abc12345xyz，别告诉别人",
            "password: Tr0ub4dor&3!!",
            "passwd=abcdefg",
            "password: 123456",
            "secret: abcdef1234",
            "SECRET=ab12cd34",
        ],
    )
    def test_a_password_the_text_gives_is_refused(self, statement: str) -> None:
        assert _rules(statement) == ["plaintext_credential"]

    @pytest.mark.parametrize(
        "statement",
        ["password policy requires rotation", "用户忘记了密码，需要重置流程", "the secret: we ship on Friday"],
    )
    def test_talking_about_passwords_is_not_giving_one(self, statement: str) -> None:
        assert _GATE.inspect(statement).is_clean


class TestMasking:
    def test_only_the_sensitive_characters_are_replaced(self) -> None:
        result = _MASKING_GATE.inspect("order 1234567890123456 shipped; card 4111 1111 1111 1111")

        assert result.sanitized_text == "order 1234567890123456 shipped; card [credit_card_REDACTED]"

    def test_an_iban_is_replaced_and_a_courier_number_beside_it_is_kept(self) -> None:
        result = _MASKING_GATE.inspect("pay to DE89 3704 0044 0532 0130 00 and ref SF1234567890123")

        assert result.sanitized_text == "pay to [iban_REDACTED] and ref SF1234567890123"

    def test_every_kind_is_replaced_in_place_and_the_password_label_is_kept(self) -> None:
        result = _MASKING_GATE.inspect("password: Tr0ub4dor&3!!, ssn 123-45-6789 and 身份证 11010519491231002X")

        assert result.sanitized_text == (
            "password: [plaintext_credential_REDACTED], ssn [ssn_us_REDACTED] and 身份证 [national_id_cn_REDACTED]"
        )

    def test_a_clean_statement_comes_back_unchanged(self) -> None:
        statement = "用户喜欢在周六上午九点跑步，偏好深色运动服。"

        result = _MASKING_GATE.inspect(statement)

        assert result.is_clean
        assert result.sanitized_text == statement

    def test_rejecting_mode_leaves_the_statement_as_it_was(self) -> None:
        statement = "卡号 4111 1111 1111 1111"

        assert _GATE.inspect(statement).sanitized_text == statement


class TestAuditTrail:
    def test_an_identifier_shows_its_first_and_last_two_characters_and_a_card_is_high_severity(self) -> None:
        violation = _GATE.inspect("卡号 4111 1111 1111 1111").violations[0]

        assert violation.snippet_masked == "41" + "*" * 15 + "11"
        assert violation.severity == "high"

    def test_a_credential_is_never_shown(self) -> None:
        violation = _GATE.inspect("password: Tr0ub4dor&3!!").violations[0]

        assert violation.snippet_masked == "***"
        assert violation.severity == "critical"

    def test_is_safe_for_storage_agrees_with_inspect(self) -> None:
        assert _GATE.is_safe_for_storage("用户常驻北京，喜欢周末徒步。")
        assert not _GATE.is_safe_for_storage("卡号 4111 1111 1111 1111")


class TestAgreementWithThePrivacyPipeline:
    @pytest.mark.parametrize("number", _PUBLISHED_CARDS)
    def test_a_number_the_classifier_calls_confidential_is_refused(self, number: str) -> None:
        statement = f"my card is {number} thanks"

        assert classify_content(statement, PrivacyPolicy(enabled=True)).level == SensitivityLevel.S3
        assert not _GATE.is_safe_for_storage(statement)

    def test_switching_privacy_off_never_lets_a_card_into_memory(self) -> None:
        statement = "用户的卡号是 4111 1111 1111 1111"

        assert classify_content(statement, PrivacyPolicy(enabled=False)).level == SensitivityLevel.S1
        assert not _GATE.is_safe_for_storage(statement)
