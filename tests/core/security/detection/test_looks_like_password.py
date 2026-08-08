"""Tests for the conservative password-like heuristic in leak_detector."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.detection.leak_detector import looks_like_password


class TestLooksLikePassword:
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
        ids=["sentence", "colon", "py-assign", "env-assign", "json", "master",
             "otp-numeric", "pin-numeric", "2fa-numeric", "zh-verification-code",
             "otp-not-phone", "otp-after-year", "otp-before-keyword",
             "otp-before-adjacent", "short-strong-password", "short-strong-password2"],
    )
    def test_detects_password_like(self, text: str) -> None:
        assert looks_like_password(text) is not None

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
            "The password is abcd12",  # weak: lower+digit, no mixed case/symbol
            "",
        ],
        ids=["clean-sentence", "branch", "ask-delete", "no-token", "short-password",
             "numeric-only", "bare-numeric", "otp-no-value", "pin-verb", "no-keyword",
             "zh-otp-no-value", "otp-no-code", "passcode-too-long", "code-too-short",
             "year-after-2fa", "year-after-otp", "year-after-pin", "phone-before-otp",
             "phone-adjacent-otp", "weak-password", "empty"],
    )
    def test_benign_text_no_password(self, text: str) -> None:
        assert looks_like_password(text) is None
