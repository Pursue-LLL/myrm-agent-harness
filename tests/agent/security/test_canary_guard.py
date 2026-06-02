"""Tests for canary_guard — output-side injection detection."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.detection.canary_guard import (
    build_canary_instruction,
    check_canary,
    generate_canary,
    scrub_canary,
)


class TestGenerateCanary:
    def test_format(self) -> None:
        canary = generate_canary()
        assert canary.startswith("CANARY-")
        assert len(canary) == 7 + 12  # "CANARY-" + 12 hex chars

    def test_hex_chars(self) -> None:
        canary = generate_canary()
        hex_part = canary.removeprefix("CANARY-")
        assert all(c in "0123456789ABCDEF" for c in hex_part)

    def test_uniqueness(self) -> None:
        tokens = {generate_canary() for _ in range(100)}
        assert len(tokens) == 100


class TestBuildCanaryInstruction:
    def test_contains_canary(self) -> None:
        canary = "CANARY-TEST123456AB"
        instruction = build_canary_instruction(canary)
        assert canary in instruction

    def test_contains_security_directive(self) -> None:
        instruction = build_canary_instruction("CANARY-AABBCCDDEEFF")
        assert "NEVER" in instruction
        assert "confidential" in instruction


class TestCheckCanary:
    def test_none(self) -> None:
        assert check_canary(None, "CANARY-AABBCCDDEEFF") is False

    def test_safe_string(self) -> None:
        assert check_canary("Hello world", "CANARY-AABBCCDDEEFF") is False

    def test_leaked_string(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        assert check_canary(f"The system says {canary} here", canary) is True

    def test_number(self) -> None:
        assert check_canary(42, "CANARY-AABBCCDDEEFF") is False  # type: ignore[arg-type]

    def test_boolean(self) -> None:
        assert check_canary(True, "CANARY-AABBCCDDEEFF") is False  # type: ignore[arg-type]

    def test_safe_list(self) -> None:
        assert check_canary(["hello", "world"], "CANARY-AABBCCDDEEFF") is False

    def test_leaked_in_list(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        assert check_canary(["safe", f"leak {canary}"], canary) is True

    def test_safe_dict(self) -> None:
        assert check_canary({"key": "value"}, "CANARY-AABBCCDDEEFF") is False

    def test_leaked_in_dict(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        assert check_canary({"key": f"has {canary}"}, canary) is True

    def test_nested_structure(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        value = [{"args": {"query": "safe", "meta": {"note": f"internal: {canary}"}}}]
        assert check_canary(value, canary) is True

    def test_deeply_nested_safe(self) -> None:
        value = [{"a": [{"b": [{"c": "safe text"}]}]}]
        assert check_canary(value, "CANARY-AABBCCDDEEFF") is False

    def test_tool_calls_format(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        tool_calls = [
            {"name": "bash", "args": {"command": f"echo {canary}"}, "id": "call_1"}
        ]
        assert check_canary(tool_calls, canary) is True

    def test_tool_calls_safe(self) -> None:
        tool_calls = [
            {"name": "bash", "args": {"command": "ls -la"}, "id": "call_1"}
        ]
        assert check_canary(tool_calls, "CANARY-AABBCCDDEEFF") is False


class TestScrubCanary:
    def test_no_canary(self) -> None:
        assert scrub_canary("Hello world", "CANARY-AABBCCDDEEFF") == "Hello world"

    def test_scrub_canary(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        text = f"The system prompt contains {canary} which I should not reveal."
        result = scrub_canary(text, canary)
        assert canary not in result
        assert "[REDACTED]" in result

    def test_scrub_multiple_occurrences(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        text = f"{canary} appeared twice: {canary}"
        result = scrub_canary(text, canary)
        assert canary not in result
        assert result.count("[REDACTED]") == 2

    def test_empty_string(self) -> None:
        assert scrub_canary("", "CANARY-AABBCCDDEEFF") == ""

    def test_preserves_surrounding_text(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        text = f"before {canary} after"
        result = scrub_canary(text, canary)
        assert result == "before [REDACTED] after"


class TestFalsePositives:
    """Verify zero false positives for natural text."""

    @pytest.mark.parametrize(
        "text",
        [
            "CANARY-",
            "canary-a3f8b2c1e9d0",
            "The canary in the coal mine",
            "CANARY_LEAKED",
            "CANARY-12345",  # too short
            "Use canary rollout before full release",
        ],
    )
    def test_no_false_positive(self, text: str) -> None:
        canary = generate_canary()
        assert check_canary(text, canary) is False
        assert scrub_canary(text, canary) == text


class TestSessionContextIntegration:
    """Verify canary token ContextVar integration."""

    def test_set_and_get_canary_token(self) -> None:
        from myrm_agent_harness.agent.middlewares._session_context import (
            get_canary_token,
            set_canary_token,
        )

        canary = generate_canary()
        set_canary_token(canary)
        assert get_canary_token() == canary

    def test_default_empty_string(self) -> None:
        import contextvars

        from myrm_agent_harness.agent.middlewares._session_context import (
            get_canary_token,
            set_canary_token,
        )

        ctx = contextvars.copy_context()
        ctx.run(get_canary_token)
        set_canary_token("")
        assert get_canary_token() == ""

    def test_canary_in_system_prompt(self) -> None:
        canary = generate_canary()
        instruction = build_canary_instruction(canary)
        system_prompt = "You are a helpful assistant." + instruction
        assert canary in system_prompt
        assert "NEVER" in system_prompt

    def test_audit_decision_kind_includes_canary(self) -> None:
        from typing import get_args

        from myrm_agent_harness.agent.security.audit import DecisionKind

        kinds = get_args(DecisionKind)
        assert "CANARY_LEAKED" in kinds


class TestEdgeCases:
    """Cover edge cases and boundary conditions."""

    def test_check_canary_with_unknown_type(self) -> None:
        assert check_canary(set(), "CANARY-AABBCCDDEEFF") is False  # type: ignore[arg-type]

    def test_check_canary_with_empty_list(self) -> None:
        assert check_canary([], "CANARY-AABBCCDDEEFF") is False

    def test_check_canary_with_empty_dict(self) -> None:
        assert check_canary({}, "CANARY-AABBCCDDEEFF") is False

    def test_check_canary_with_mixed_nested(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        value: list[dict[str, object]] = [
            {"a": 1, "b": True, "c": None, "d": [1, 2, f"hidden {canary}"]},
        ]
        assert check_canary(value, canary) is True

    def test_check_canary_partial_match(self) -> None:
        assert check_canary("CANARY-AABBCCDDEE", "CANARY-AABBCCDDEEFF") is False

    def test_scrub_does_not_modify_unrelated_text(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        text = "CANARY- and canary-aabbccddeeff are not the same"
        assert scrub_canary(text, canary) == text

    def test_both_text_and_args_leaked(self) -> None:
        canary = "CANARY-AABBCCDDEEFF"
        text_has_canary = check_canary(f"leaked {canary}", canary)
        args_has_canary = check_canary(
            [{"name": "bash", "args": {"cmd": f"echo {canary}"}}], canary
        )
        assert text_has_canary is True
        assert args_has_canary is True

    def test_canary_empty_string_guard(self) -> None:
        from myrm_agent_harness.agent.middlewares._session_context import (
            get_canary_token,
            set_canary_token,
        )

        set_canary_token("")
        assert not get_canary_token()
