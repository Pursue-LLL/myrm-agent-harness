"""Tests for the shared "secret value or reference to one" rules."""

from __future__ import annotations

import random
import string
import time
from collections.abc import Callable

import pytest

from myrm_agent_harness.core.security.detection.secret_value import (
    is_reference_token,
    is_reference_value,
    secret_value_span,
)

_MIN_TOKEN_LENGTH = 24


class TestIsReferenceValue:
    @pytest.mark.parametrize(
        ("value", "key"),
        [
            ("{token_efficiency:.2f}", "token"),
            ("{password}", "password"),
            ("<your-password>", "password"),
            ("$DB_PASSWORD", "password"),
            ("$password", "password"),
            ("${DB_PASSWORD}", "password"),
            ("$(cat /run/secrets/pw)", "password"),
            ("%(password)s", "password"),
            ("%APPDATA%", "token"),
            ("settings.DB_PASSWORD", "password"),
            ("status.HTTP_400_BAD_REQUEST", "token"),
            ("AuthType.OAUTH2_CLIENT_CREDENTIALS", "credentials"),
            ("apiKey?.trim", "api_key"),
            ("_resolve_clawhub_token()", "token"),
            ("_active_value(settings,", "token"),
            ("self._credentials.get_key(name)", "api_key"),
            ("a-zA-Z0-9_", "password"),
            ("A-Za-z0-9_", "token"),
            ("\\s+https?", "password"),
            ("passphrase", "passphrase"),
            ("PASS_WORD", "password"),
            ("config.remote_token,", "token"),
            ("self._config.password)", "password"),
            ("transport_secret,", "transport_secret"),
            ("failure_alert_secret,", "delivery_secret"),
            ("getAuthenticationToken)", "token"),
            ("process.env.GROQ_API_KEY!", "api_key"),
            ("process.env.INTELLIGENCE_API_KEY!,", "api_key"),
            ("import.meta.env?.VITE_TOKEN!", "token"),
        ],
    )
    def test_reference_is_not_a_secret(self, value: str, key: str) -> None:
        assert is_reference_value(value, key=key)

    @pytest.mark.parametrize(
        ("value", "key"),
        [
            ("Zk9%mango42", "password"),
            ("Pa$$w0rd2024", "password"),
            ("ab$cdef1234567", "api_key"),
            ("Zk9$mango42xyz", "secret"),
            ("$ecretPass1", "password"),
            ("superSecret123", "password"),
            ("MyDogRex2024", "password"),
            ("e2e_settings_secret", "secret"),
            ("my_secret_2024", "password"),
            ("myrm-diagnostic-hmac-v1-secret", "secret"),
            ("hunter2hunter2", "password"),
            ("Tr0ub4dor&3", "password"),
            ("Summer.2024", "password"),
            ("dragonfly12", "password"),
            ("a1b2c3d4e5f60718293a4b5c6d7e8f90.aB3xK9mW2pQ7vL4n", "api_key"),
            ("my_long_secret_word", "secret"),
            ("MY_LONG_SECRET_WORD", "secret"),
            ("currentPasswordValue", "password"),
            ("abcdef1234567890abcd,", "api_key"),
            ("%CShtiyZGp3Es5t%", "password"),
            ("john.Smith2024", "password"),
            ("4iTHeH\\Dp", "password"),
            ("SEnXmn51VhZ\\\\SD", "password"),
            ("k\\uK6tW1-d\\dxKQ", "password"),
            ("john.smith!", "password"),
            ("my.pass1!", "password"),
            ("Zk9#mango42!", "password"),
            ("process.env.GROQ_API_KEY!x", "api_key"),
        ],
    )
    def test_secret_is_not_a_reference(self, value: str, key: str) -> None:
        assert not is_reference_value(value, key=key)


class TestIsReferenceToken:
    @pytest.mark.parametrize(
        "token",
        [
            "status.HTTP_400_BAD_REQUEST",
            "ledger.gate_verdict.DeliveryVerdict.PASS_100",
            "UserAuthenticationServiceImplementation2",
            "OpenHTTPServerRequestHandlerFactory",
            "model_name=claude-sonnet-4-5-20250929-preview",
            "very_long_keyword_argument_name=abc123",
            "my_very_long_snake_case_name_v2",
            "alice.longname1@example-company-domain.com",
            "q=machine-learning-papers2024&page=2",
            "docs/search?q=machine-learning-papers2024",
        ],
    )
    def test_identifier_slug_address_or_query_is_not_a_credential(self, token: str) -> None:
        assert is_reference_token(token, min_length=_MIN_TOKEN_LENGTH)

    @pytest.mark.parametrize(
        "token",
        [
            "aB3xK9mW2pQ7vL4nR8sT1yU6hD0jF5cG",
            "X7k9M2pQvL4nR8s1T6hD0jF5cGaB3xK9",
            "secret_blob=X7k9M2pQvL4nR8s1T6hD0jF5cGaB3xK9",
            "a1b2c3d4e5f60718293a4b5c6d7e8f90.aB3xK9mW2pQ7vL4n",
            "Xk9mPq2LwR7vNb3TcY5d.Hf8Js1Ku6Gz4Ae0Mo2W",
            "docs/search?token=aB3xK9mW2pQ7vL4nR8sT1yU6hD0jF5cG&page=2",
            "callback?api_key=X7k9M2pQvL4nR8s1T6hD0jF5cGaB3xK9&x=1",
            "aB3xK9mW2pQ7vL4nR8sT1yU6hD0jF5cG@internal",
        ],
    )
    def test_random_looking_token_stays_a_credential(self, token: str) -> None:
        assert not is_reference_token(token, min_length=_MIN_TOKEN_LENGTH)

    def test_generated_tokens_are_never_taken_for_references(self) -> None:
        rng = random.Random(20261013)
        alphabets = {
            "base62": string.ascii_letters + string.digits,
            "urlsafe": string.ascii_letters + string.digits + "_-",
            "lower-base36": string.ascii_lowercase + string.digits + "_-",
            "upper-base36": string.ascii_uppercase + string.digits + "_-",
        }

        def draw(alphabet: str) -> str:
            return "".join(rng.choice(alphabet) for _ in range(rng.randint(_MIN_TOKEN_LENGTH, 40)))

        shapes: dict[str, Callable[[str], str]] = {
            "bare": draw,
            "dotted": lambda alphabet: f"{draw(alphabet)}.{draw(alphabet)}",
            "query": lambda alphabet: f"docs/search?token={draw(alphabet)}&page=2",
            "address": lambda alphabet: f"{draw(alphabet)}@internal",
        }
        for alphabet in alphabets.values():
            for shape in shapes.values():
                tokens = [shape(alphabet) for _ in range(300)]
                assert [t for t in tokens if is_reference_token(t, min_length=_MIN_TOKEN_LENGTH)] == []


class TestLinearTime:
    """Scanners run on untrusted text, so no input may make a rule backtrack exponentially."""

    @pytest.mark.parametrize(
        "token",
        [
            "A" * 200 + "1a!",
            "AB1" * 100 + "x!",
            "Abc" * 300 + "1_",
            "a_" * 50_000,
            "ab_" * 50_000 + "(",
            ("a" * 30 + ".") * 3_000 + "!",
            "1" * 100_000,
            "a" * 100_000 + "1a",
            "HTTPServer" * 10_000 + "9",
            "A" * 100_000 + "b",
        ],
    )
    def test_adversarial_input_is_judged_quickly(self, token: str) -> None:
        started = time.perf_counter()
        is_reference_token(token, min_length=_MIN_TOKEN_LENGTH)
        is_reference_value(token, key="password")
        assert time.perf_counter() - started < 1.0


class TestSecretValueSpan:
    @pytest.mark.parametrize(
        "value",
        [
            "short1",  # shorter than 8
            "12345678901",  # purely numeric example
            "required",  # field state word
            "********",  # mask
            "xxxxxxxx",  # mask
            "settings.DB_PASSWORD",  # attribute reference
            "DB_PASSWORD",  # constant reference
            "password_hash",  # snake-case identifier
            "Optional[str]",  # type annotation
            "${DB_PASSWORD}",  # template
            "https://example.com/p?x=1",  # URL
            "[REDACTED]",  # already redacted
            "[REDACTED:env_credential]",  # already redacted by the leak detector
            "currentPassword",  # camel-case reference
            "vaultPassword",  # camel-case reference
            "_private_name",  # private snake-case name
            "_LOCAL_NO_AUTH_KEY_MARKER",  # private constant
            "a-zA-Z0-9_",  # regex character class
        ],
    )
    def test_rejects_non_secret_values(self, value: str) -> None:
        assert secret_value_span(value, 0, len(value), allow_letters_only=True) is None

    @pytest.mark.parametrize("value", ["Zk9%mango42", "Pa$$w0rd2024", "ab$cdef1234567", "Zk9$mango42xyz"])
    def test_dollar_and_percent_inside_a_value_are_password_characters(self, value: str) -> None:
        assert secret_value_span(value, 0, len(value), allow_letters_only=False) == (0, len(value))

    def test_letters_only_value_passes_only_for_a_password_label(self) -> None:
        text = "dragonfly"
        assert secret_value_span(text, 0, len(text), allow_letters_only=True) == (0, len(text))
        assert secret_value_span(text, 0, len(text), allow_letters_only=False) is None

    def test_minimum_length_is_the_callers_choice(self) -> None:
        text = "abcd1234efgh"
        assert secret_value_span(text, 0, len(text), allow_letters_only=False) == (0, len(text))
        assert secret_value_span(text, 0, len(text), allow_letters_only=False, min_length=16) is None

    def test_trims_quotes_and_sentence_punctuation_but_keeps_trailing_strong_symbol(self) -> None:
        text = '"Zk9#mango42!".'
        start, end = secret_value_span(text, 0, len(text), allow_letters_only=False) or (0, 0)
        assert text[start:end] == "Zk9#mango42!"

    def test_closing_bracket_after_the_raw_span_still_makes_a_template(self) -> None:
        text = "{token_efficiency:.2f}"
        assert secret_value_span(text, 0, len(text) - 1, allow_letters_only=False, min_length=16) is None

    def test_braces_that_do_not_end_the_value_are_part_of_the_secret(self) -> None:
        text = "{Iw7UKmeD3}3&"
        assert secret_value_span(text, 0, 10, allow_letters_only=False) == (1, 10)

    def test_value_equal_to_its_key_is_a_pass_through(self) -> None:
        text = "passphrase"
        assert secret_value_span(text, 0, len(text), allow_letters_only=True) == (0, len(text))
        assert secret_value_span(text, 0, len(text), allow_letters_only=True, key="passphrase") is None

    def test_camel_case_is_a_reference_unless_the_text_quotes_it(self) -> None:
        bare = "currentPassword"
        quoted = '"currentPassword"'
        assert secret_value_span(bare, 0, len(bare), allow_letters_only=True) is None
        assert secret_value_span(quoted, 1, len(quoted) - 1, allow_letters_only=True) == (1, len(quoted) - 1)
