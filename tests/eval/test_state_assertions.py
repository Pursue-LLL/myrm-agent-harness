"""Tests for the state assertion engine (evaluate_state_assertions)."""

import json


class TestStateAssertions:
    """Tests for evaluate_state_assertions including new types."""

    def test_empty(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions

        passed, details = evaluate_state_assertions([], "output")
        assert passed is None
        assert details is None

    def test_contains(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, _ = evaluate_state_assertions([StateAssertion(type="contains", expected="hello")], "hello world")
        assert passed is True

        passed, _details = evaluate_state_assertions(
            [StateAssertion(type="contains", expected="missing")], "hello world"
        )
        assert passed is False

    def test_not_contains(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="not_contains", expected="error")], "success result"
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="not_contains", expected="error")], "an error occurred"
        )
        assert passed is False
        assert "must NOT contain" in details

    def test_regex(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="regex", expected=r"\d{4}-\d{2}-\d{2}")],
            "Date: 2024-01-15",
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="regex", expected=r"\d{4}-\d{2}-\d{2}")],
            "no date here",
        )
        assert passed is False
        assert "does not match regex" in details

    def test_json_valid(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_valid", expected="")], '{"key": "value"}'
        )
        assert passed is True

        passed, details = evaluate_state_assertions([StateAssertion(type="json_valid", expected="")], "not json")
        assert passed is False
        assert "not valid JSON" in details

    def test_json_schema(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        schema = json.dumps({"required": ["name", "age"]})
        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected=schema)],
            '{"name": "Alice", "age": 30}',
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected=schema)], '{"name": "Alice"}'
        )
        assert passed is False
        assert "Missing required field" in details

    def test_json_schema_with_type_check(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        schema = json.dumps({"properties": {"age": {"type": "integer"}}})
        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected=schema)], '{"age": 30}'
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected=schema)], '{"age": "thirty"}'
        )
        assert passed is False
        assert "expected type" in details

    def test_custom_python(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="custom_python", expected="len(output) < 100")],
            "short text",
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="custom_python", expected="len(output) < 5")],
            "this is too long",
        )
        assert passed is False
        assert "evaluated to False" in details

    def test_custom_python_error(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="custom_python", expected="undefined_var")], "output"
        )
        assert passed is False
        assert "custom expression error" in details

    def test_exact_match(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, _ = evaluate_state_assertions([StateAssertion(type="exact_match", expected="hello")], "hello")
        assert passed is True

        passed, _details = evaluate_state_assertions(
            [StateAssertion(type="exact_match", expected="hello")], "hello world"
        )
        assert passed is False

    def test_unknown_type(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions([StateAssertion(type="nonexistent", expected="x")], "output")
        assert passed is False
        assert "Unknown assertion type" in details


class TestStateAssertionBranches:
    """Edge branches of evaluate_state_assertions."""

    def test_json_schema_output_not_json(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected='{"required": ["name"]}')],
            "not json at all",
        )
        assert passed is False
        assert "json_schema requires valid JSON" in details

    def test_json_schema_invalid_schema(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected="not-a-json-schema")],
            '{"name": "Alice"}',
        )
        assert passed is False
        assert "invalid JSON schema definition" in details

    def test_jaccard_similarity_below_threshold(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [
                StateAssertion(
                    type="jaccard_similarity",
                    expected="completely unrelated topic words",
                    threshold=0.9,
                )
            ],
            "hello world",
        )
        assert passed is False
        assert "below threshold" in details

    def test_jaccard_similarity_pass(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, _ = evaluate_state_assertions(
            [StateAssertion(type="jaccard_similarity", expected="hello world", threshold=0.5)],
            "hello world again",
        )
        assert passed is True

    def test_schema_must_be_object(self):
        from myrm_agent_harness.eval.assertions import _validate_json_schema

        assert _validate_json_schema({"a": 1}, "not-a-dict") == "Schema must be a JSON object"  # type: ignore[arg-type]
        assert _validate_json_schema({"a": 1}, {"required": ["a"]}) is None

    def test_check_json_type_unknown(self):
        from myrm_agent_harness.eval.assertions import _check_json_type

        assert _check_json_type("x", "unknown_type") is True
