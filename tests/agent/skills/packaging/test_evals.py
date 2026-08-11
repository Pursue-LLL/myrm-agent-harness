"""Tests for packaging/evals.py serialization primitives."""

import json

import pytest

from myrm_agent_harness.agent.skills.packaging.evals import (
    EVALS_FILE,
    EVALS_SCHEMA_VERSION,
    is_evals_file,
    parse_evals_json,
    serialize_eval_cases,
)


EVAL_CASES = [
    {
        "message": "sum the numbers 1 and 2",
        "expected_tools": ["code_interpreter"],
        "require_all": True,
        "metadata": {"severity": "high"},
    },
    {
        "message": "query sales for March",
        "sandbox_assertions": [{"type": "db_query", "query": "SELECT * FROM sales WHERE month='march'"}],
    },
]


def test_serialize_roundtrip():
    content = serialize_eval_cases("my_skill", EVAL_CASES)

    parsed = json.loads(content)
    assert parsed["schema_version"] == EVALS_SCHEMA_VERSION
    assert parsed["skill_name"] == "my_skill"
    assert parsed["evals"] == EVAL_CASES


def test_parse_evals_json_roundtrip():
    content = serialize_eval_cases("my_skill", EVAL_CASES)
    assert parse_evals_json(content) == EVAL_CASES


def test_parse_evals_json_accepts_bytes():
    content = serialize_eval_cases("my_skill", EVAL_CASES)
    assert parse_evals_json(content.encode("utf-8")) == EVAL_CASES


def test_parse_evals_json_empty_evals():
    content = serialize_eval_cases("my_skill", [])
    assert parse_evals_json(content) == []


def test_parse_evals_json_invalid_json():
    assert parse_evals_json("{not valid json") is None


def test_parse_evals_json_unsupported_schema_version():
    content = json.dumps({"schema_version": EVALS_SCHEMA_VERSION + 1, "skill_name": "s", "evals": []})
    assert parse_evals_json(content) is None


def test_parse_evals_json_non_object_entries():
    content = json.dumps({"schema_version": EVALS_SCHEMA_VERSION, "skill_name": "s", "evals": ["nope", 42]})
    assert parse_evals_json(content) is None


def test_parse_evals_json_missing_evals_key():
    content = json.dumps({"schema_version": EVALS_SCHEMA_VERSION, "skill_name": "s"})
    assert parse_evals_json(content) is None


def test_parse_evals_json_top_level_not_dict():
    assert parse_evals_json("[1, 2, 3]") is None


def test_is_evals_file():
    assert is_evals_file("evals.json")
    assert is_evals_file("my_skill/evals.json")
    assert not is_evals_file("evals.json.bak")
    assert not is_evals_file("data/evals_data.json")
    assert not is_evals_file("SKILL.md")
