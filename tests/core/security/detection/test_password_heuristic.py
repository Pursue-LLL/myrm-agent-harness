"""Tests for the keyword-anchored password heuristic."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.detection.password_heuristic import find_password_spans


def _secrets(text: str) -> list[str]:
    return [text[start:end] for start, end in find_password_spans(text)]


class TestFindPasswordSpans:
    @pytest.mark.parametrize(
        "text",
        [
            "The staging password is Zk9#mango42 - remember it, we never rotate it.",
            "The password for staging: Zk9#mango42",
            'password = "Zk9#mango42"',
            "PASSWD=Zk9#mango42",
            '{"password": "Zk9#mango42"}',
            "master password: Ab1!cd2@ef",
            "The OTP code is 582013 - enter it within 30 seconds.",
            "The staging PIN is 482913.",
            "2FA code: 449271, do not share it.",
            "你的验证码是 582013，请勿转发。",
            "My phone number is 13800138000 and the OTP code is 582013.",
            "2024, the OTP is 582013.",
            "use 582013 as the OTP.",
            "582013 is my OTP.",
            "Wifi password: Ab1!cd",
            "staging pwd: aB3!xyz",
        ],
        ids=[
            "sentence",
            "colon",
            "py-assign",
            "env-assign",
            "json",
            "master",
            "otp-numeric",
            "pin-numeric",
            "2fa-numeric",
            "zh-verification-code",
            "otp-not-phone",
            "otp-after-year",
            "otp-before-keyword",
            "otp-before-adjacent",
            "short-strong-password",
            "short-strong-password2",
        ],
    )
    def test_detects_password_like(self, text: str) -> None:
        assert find_password_spans(text)

    @pytest.mark.parametrize(
        "text",
        [
            "I prefer short, direct answers that cite sources.",
            "I only push to the develop branch, never straight to main.",
            "Please always ask before deleting files.",
            "The staging password is being rotated quarterly.",
            "password: hunter2",  # too short
            "password: 1234567890",  # generic password + numeric example stays benign
            "The code is 482913.",  # numeric without a credential keyword
            "I typed the OTP into the form and it worked.",
            "PIN this note to the top of the page.",  # "pin" as a verb, not a credential
            "Use my SSH key instead of a token.",
            "验证码已发送，请查收。",  # keyword without a numeric value
            "The OTP expires soon, keep your phone nearby.",  # no numeric code value
            "passcode 1234567890123",  # 13 digits: above the 12-digit ceiling
            "code 123",  # below the 4-digit floor
            "The 2FA was enabled since 2024 on the main account.",  # year, not an OTP
            "OTP expires in 2026-03-15, renewal yearly.",  # year, not an OTP
            "PIN code was set in 2020.",  # year, not a PIN
            "My phone is 13800138000, what's the OTP?",  # phone, no code after kw
            "my phone 13800138000 is the OTP.",  # CN mobile adjacent to kw
            "The password is abcd12",  # weak: shorter than 8
            "",
        ],
        ids=[
            "clean-sentence",
            "branch",
            "ask-delete",
            "no-token",
            "short-password",
            "numeric-only",
            "bare-numeric",
            "otp-no-value",
            "pin-verb",
            "no-keyword",
            "zh-otp-no-value",
            "otp-no-code",
            "passcode-too-long",
            "code-too-short",
            "year-after-2fa",
            "year-after-otp",
            "year-after-pin",
            "phone-before-otp",
            "phone-adjacent-otp",
            "weak-password",
            "empty",
        ],
    )
    def test_benign_text_no_password(self, text: str) -> None:
        assert find_password_spans(text) == []


class TestSecretIsExactlyTheSpan:
    """Persistence redacts exactly the returned span, so it must be the secret itself."""

    @pytest.mark.parametrize(
        ("text", "secret"),
        [
            ("Password: Zk9#mango42", "Zk9#mango42"),
            ("Please remember: my wifi password is Zk9#mango42", "Zk9#mango42"),
            ("My Passcode is Xk7!mQ2z", "Xk7!mQ2z"),
            ("The staging password is Hunter2-Zq9!x", "Hunter2-Zq9!x"),
            ("password: Ab1/cd2~ef", "Ab1/cd2~ef"),
            ("Wifi password: xK9-mPq2-Lw8z.", "xK9-mPq2-Lw8z"),
            ("PASSWD=Zk9#mango42", "Zk9#mango42"),
            ("password reset link: https://example.com/reset, new password Zk9#mango42", "Zk9#mango42"),
            ("password: Welcome1!", "Welcome1!"),
            ("My password is Zk9#mango42! Please keep it", "Zk9#mango42!"),
            ("password: @Zk9mango42", "@Zk9mango42"),
            ("The Wi-Fi password for MyHome-5G is Tr0ub4dor&3", "Tr0ub4dor&3"),
            ("The password is SuperSecret123.", "SuperSecret123"),
            ("Use Zk9#mango42 as the password", "Zk9#mango42"),
            ("Password: **Zk9#mango42**", "Zk9#mango42"),
            ("**Password**: Zk9#mango42", "Zk9#mango42"),
            ("my pin is 482913", "482913"),
            ("Pin: 482913", "482913"),
            ("PIN 482913", "482913"),
            ("my atm pin 482913", "482913"),
            ("pin code 482913", "482913"),
            ("The OTP is **582013**", "582013"),
        ],
        ids=[
            "capitalised-keyword",
            "leading-capitalised-word",
            "capitalised-passcode-keyword",
            "hyphenated-secret",
            "slash-and-tilde-secret",
            "dash-separated-generated",
            "env-assignment-keeps-label",
            "url-before-secret",
            "trailing-symbol-belongs-to-secret",
            "trailing-symbol-before-prose",
            "leading-symbol-belongs-to-secret",
            "secret-beats-hyphenated-network-name",
            "sentence-final-period-is-not-the-secret",
            "generated-token-before-keyword",
            "markdown-bold-value-keeps-markup",
            "markdown-bold-label",
            "pin-lowercase-introduced-by-is",
            "pin-titlecase-introduced-by-colon",
            "pin-uppercase-acronym-needs-no-connector",
            "pin-lowercase-directly-followed-by-code",
            "pin-code-label-directly-followed-by-code",
            "markdown-bold-code",
        ],
    )
    def test_returns_the_secret_not_a_neighbouring_word(self, text: str, secret: str) -> None:
        assert _secrets(text) == [secret]

    @pytest.mark.parametrize(
        ("text", "secret"),
        [
            ("my netflix password is mypassword123", "mypassword123"),
            ("我的银行卡密码是 abc123456", "abc123456"),
            ("我的密码是Zk9#mango42", "Zk9#mango42"),
            ("密码：abc123456，请勿转发。", "abc123456"),
            ("密码改成 hello12345678", "hello12345678"),
            ("Please set the password to Tr0ub4dor&3 today.", "Tr0ub4dor&3"),
            ("login: bob / password: dragonfly1", "dragonfly1"),
        ],
        ids=["lower-digit", "zh-space", "zh-no-space", "zh-colon", "zh-change-to", "set-to", "login-pair"],
    )
    def test_value_introduced_by_the_text_needs_no_generated_look(self, text: str, secret: str) -> None:
        assert _secrets(text) == [secret]

    @pytest.mark.parametrize(
        ("text", "secrets"),
        [
            ("old password is Ab1!cd2@ef, new password is Zk9#mango42", ["Ab1!cd2@ef", "Zk9#mango42"]),
            ("wifi password is hunter2hunter2 and the PIN is 482913", ["hunter2hunter2", "482913"]),
            ("The PIN is 482913 and the OTP is 582013.", ["482913", "582013"]),
        ],
        ids=["two-passwords", "password-and-pin", "pin-and-otp"],
    )
    def test_every_keyword_occurrence_is_anchored_separately(self, text: str, secrets: list[str]) -> None:
        assert _secrets(text) == secrets


class TestProseIsNeverASecret:
    @pytest.mark.parametrize(
        "text",
        [
            "My password is stored in the Password-Manager app",
            "The password reset page is at Example.com/Reset",
            "Two-Factor-Authentication replaced the old password flow",
            "Employees must rotate the password regularly. Always use a password manager.",
            "1Password and Bitwarden are password managers. Please evaluate Dashlane.",
            "Remember to pin the message in the group. Developers should read Onboarding first.",
            "Run pwd to print the working directory. Contributors must follow Conventions.",
            "I forgot my password on my iPhone15Pro again, so I used Face ID.",
            "Merge pull request #1622: test(iam): pin service lifecycle",
            "chore(macos): update Peekaboo to 4.9.0 (#166615)\n\nPin the macOS app to the toolchain.",
            "bump maqami-travel pin to d7c4efd 1239025194 2026-10-07",
            "分片连播 `10120-10169` 并 pin `playback` 状态",
            "内置 TOTP（RFC 6238）：2FA 自动化，无需第三方 TOTP 应用",
            "**过期（无论是否密码保护）一律视为 unshared**）/ revoked",
            "| 验证码 | 无 | **CAPTCHA 检测器** | | 登录支持 | 扫码登录 | **OAuth2 + 异步登录",
            "| **P1-PairRevoke** | WebUI 改密/启用密码保护时轮换 `pairing`",
            "密码、Token、私钥瞬间转为 `***REDACTED***`，杜绝明文落盘",
            "support email OTP credentials in Copilot (#6716)",
            "pin 3 messages and 2024 releases to the channel",
        ],
        ids=[
            "hyphenated-product-name",
            "domain-and-path",
            "hyphenated-prose",
            "capitalised-words-around-keyword",
            "product-names",
            "pin-as-verb",
            "pwd-shell-command",
            "device-name-near-keyword",
            "pin-verb-before-pr-reference",
            "pin-verb-after-pr-reference",
            "pin-verb-before-commit-hash",
            "pin-verb-after-range",
            "spec-number-then-punctuation-then-2fa",
            "markdown-bold-word-after-connector",
            "markdown-bold-around-words",
            "markdown-bold-id-before-keyword",
            "other-redactor-banner",
            "issue-reference-after-otp",
            "pin-verb-with-short-count-and-year",
        ],
    )
    def test_prose_around_a_password_keyword_is_not_a_secret(self, text: str) -> None:
        assert find_password_spans(text) == []

    def test_keyword_far_from_words_does_not_reach_them(self) -> None:
        text = "Please read the docs. " + "Section text about onboarding. " * 30 + "Reset the password in Settings."
        assert find_password_spans(text) == []

    @pytest.mark.parametrize(
        "text",
        [
            'raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is required.")',
            r"""PAT = re.compile(r"(?i)(?:token|password)\s*[:=]\s*([a-zA-Z0-9_\-\.]{8,})")""",
            "if password == AuthType.OAUTH2_CLIENT_CREDENTIALS:",
        ],
        ids=["http-status-constant", "regex-character-class", "enum-member"],
    )
    def test_code_reference_near_a_keyword_is_not_a_generated_secret(self, text: str) -> None:
        assert find_password_spans(text) == []
