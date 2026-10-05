"""Tests for json_args_repair: escape-level args repair + invalid-call quarantine."""

from langchain_core.messages import AIMessage, ToolMessage

from myrm_agent_harness.utils.json_args_repair import (
    quarantine_invalid_tool_calls,
    repair_json_args,
)


class TestRepairJsonArgs:
    """Pure repair function — determinism, syntax-only transforms, diagnosis."""

    def test_valid_args_fast_path(self) -> None:
        result = repair_json_args('{"a": 1}')
        assert result.repaired == '{"a": 1}'
        assert result.args == {"a": 1}
        assert result.diagnosis is None

    def test_raw_control_chars_escaped(self) -> None:
        result = repair_json_args('{"path": "a\nb"}')
        assert result.args == {"path": "a\nb"}
        assert "\n" not in (result.repaired or "")

    def test_trailing_comma_stripped(self) -> None:
        result = repair_json_args('{"a": 1,}')
        assert result.args == {"a": 1}

    def test_truncated_string_closed(self) -> None:
        result = repair_json_args('{"path": "repor')
        assert result.args == {"path": "repor"}

    def test_truncated_object_closed(self) -> None:
        result = repair_json_args('{"a": {"b": 1')
        assert result.args == {"a": {"b": 1}}

    def test_truncated_array_closed(self) -> None:
        result = repair_json_args('{"items": [1, 2')
        assert result.args == {"items": [1, 2]}

    def test_truncated_mixed_nesting_closed_in_order(self) -> None:
        result = repair_json_args('{"a": [{"b": 1')
        assert result.args == {"a": [{"b": 1}]}

    def test_unbalanced_bracket_never_misrepaired(self) -> None:
        """A stray closer must not be 'repaired' into a wrong-but-parsing shape."""
        result = repair_json_args('{"a": 1]')
        assert result.repaired is None
        assert result.diagnosis is not None

    def test_truncated_container_with_trailing_comma(self) -> None:
        result = repair_json_args('{"a": 1,')
        assert result.args == {"a": 1}

    def test_dangling_escape_dropped_before_closing(self) -> None:
        result = repair_json_args('{"a": "x\\')
        assert result.args == {"a": "x"}

    def test_valid_escape_kept_when_truncated(self) -> None:
        result = repair_json_args('{"a": "x\\\\')
        assert result.args == {"a": "x\\"}

    def test_dangling_value_returns_diagnosis(self) -> None:
        result = repair_json_args('{"a": ')
        assert result.repaired is None
        assert result.args is None
        assert "failed to parse" in (result.diagnosis or "")

    def test_diagnosis_carries_key_path(self) -> None:
        result = repair_json_args('{"outer": {"inner": "v", "x": ')
        assert 'at key "outer.x"' in (result.diagnosis or "")

    def test_non_object_top_level_rejected(self) -> None:
        result = repair_json_args("[1, 2]")
        assert result.repaired is None
        assert result.args is None

    def test_empty_args_returns_diagnosis(self) -> None:
        result = repair_json_args("   ")
        assert result.repaired is None
        assert result.diagnosis is not None

    def test_repair_is_deterministic(self) -> None:
        text = '{"path": "re\npor'
        first = repair_json_args(text)
        second = repair_json_args(text)
        assert first == second


class TestQuarantineInvalidToolCalls:
    """Outbound isolation — upgrade, neutralize, sync raw payloads, idempotency."""

    @staticmethod
    def _invalid_message() -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[{"name": "good_tool", "args": {"x": 1}, "id": "c1"}],
            invalid_tool_calls=[
                {"name": "bad_tool", "args": '{"path": "repor', "id": "c2", "error": "truncated"},
                {"name": "worse_tool", "args": '{"a": ', "id": "c3", "error": "missing value"},
            ],
        )

    def test_repairable_call_upgraded_with_parsed_args(self) -> None:
        msg = self._invalid_message()
        errors = quarantine_invalid_tool_calls(msg)
        assert "c2" not in errors  # repairable → no diagnosis
        upgraded = [tc for tc in msg.tool_calls if tc["id"] == "c2"]
        assert len(upgraded) == 1
        assert upgraded[0]["name"] == "bad_tool"
        assert upgraded[0]["args"] == {"path": "repor"}
        assert msg.invalid_tool_calls == []

    def test_unrepairable_call_upgraded_with_empty_args_and_diagnosis(self) -> None:
        msg = self._invalid_message()
        quarantine_invalid_tool_calls(msg)
        upgraded = [tc for tc in msg.tool_calls if tc["id"] == "c3"]
        assert len(upgraded) == 1
        assert upgraded[0]["args"] == {}
        # diagnosis checked separately below (errors dict returned by first call)

    def test_unrepairable_returns_diagnosis_by_call_id(self) -> None:
        msg = self._invalid_message()
        errors = quarantine_invalid_tool_calls(msg)
        assert "c3" in errors
        assert "failed to parse" in errors["c3"]

    def test_valid_calls_preserved_and_upgraded_appended(self) -> None:
        msg = self._invalid_message()
        quarantine_invalid_tool_calls(msg)
        ids = [tc["id"] for tc in msg.tool_calls]
        assert ids == ["c1", "c2", "c3"]

    def test_idempotent_second_pass_noop(self) -> None:
        msg = self._invalid_message()
        first = quarantine_invalid_tool_calls(msg)
        snapshot = list(msg.tool_calls)
        second = quarantine_invalid_tool_calls(msg)
        assert second == {}
        assert first.get("c3", "").startswith("args")
        assert msg.tool_calls == snapshot

    def test_raw_payload_arguments_synced(self) -> None:
        msg = AIMessage(
            content="",
            invalid_tool_calls=[
                {"name": "bad_tool", "args": '{"path": "repor', "id": "c2", "error": "truncated"},
            ],
            additional_kwargs={
                "tool_calls": [
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {"name": "bad_tool", "arguments": '{"path": "repor'},
                    }
                ]
            },
        )
        quarantine_invalid_tool_calls(msg)
        raw = msg.additional_kwargs["tool_calls"][0]
        assert raw["function"]["arguments"] == '{"path": "repor"}'

    def test_raw_payload_synced_to_placeholder_when_unrepairable(self) -> None:
        msg = AIMessage(
            content="",
            invalid_tool_calls=[
                {"name": "bad_tool", "args": '{"a": ', "id": "c4", "error": "truncated"},
            ],
            additional_kwargs={
                "tool_calls": [
                    {
                        "id": "c4",
                        "type": "function",
                        "function": {"name": "bad_tool", "arguments": '{"a": '},
                    }
                ]
            },
        )
        errors = quarantine_invalid_tool_calls(msg)
        assert "c4" in errors
        raw = msg.additional_kwargs["tool_calls"][0]
        assert raw["function"]["arguments"] == "{}"

    def test_non_ai_message_is_noop(self) -> None:
        msg = ToolMessage(content="x", tool_call_id="c1", name="t")
        assert quarantine_invalid_tool_calls(msg) == {}

    def test_message_without_invalid_calls_is_noop(self) -> None:
        msg = AIMessage(content="hi")
        assert quarantine_invalid_tool_calls(msg) == {}

    def test_non_string_args_gets_placeholder_and_error(self) -> None:
        msg = AIMessage(
            content="",
            invalid_tool_calls=[{"name": "t", "args": None, "id": "c9", "error": "bad"}],
        )
        errors = quarantine_invalid_tool_calls(msg)
        assert "non-string" in errors["c9"]
        upgraded = [tc for tc in msg.tool_calls if tc["id"] == "c9"]
        assert upgraded[0]["args"] == {}
