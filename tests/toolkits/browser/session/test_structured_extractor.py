"""Tests for browser session StructuredExtractor raw JSON fallback parsing.

Covers the robust extraction of JSON objects/arrays from LLM responses
(fences, prose framing, trailing commas, bare control characters) used
when ``with_structured_output`` is unavailable.
"""

import pytest

from myrm_agent_harness.toolkits.browser.session.structured_extractor import (
    _extract_json_from_text,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # plain object
        ('{"name": "Alice"}', {"name": "Alice"}),
        # object wrapped in markdown fence
        ('```json\n{"name": "Alice"}\n```', {"name": "Alice"}),
        # prose framing around the object
        ("Here is the result: {\"name\": \"Alice\"} — enjoy", {"name": "Alice"}),
        # trailing comma in object
        ('{"name": "Alice",}', {"name": "Alice"}),
        # bare newline inside a string literal
        ('{"bio": "line1\nline2", "name": "Alice"}', {"bio": "line1\nline2", "name": "Alice"}),
        # multiple objects: the last parseable object wins
        ('{"example": 1} then the real one {"name": "Alice"}', {"name": "Alice"}),
    ],
)
def test_extract_json_object_robust(raw: str, expected: object) -> None:
    assert _extract_json_from_text(raw, expect_array=False) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # plain array
        ('[{"name": "A"}]', [{"name": "A"}]),
        # array with trailing comma
        ('[{"name": "A"}, {"name": "B"},]', [{"name": "A"}, {"name": "B"}]),
        # prose framing around the array
        ("Items: [{\"name\": \"A\"},] — done", [{"name": "A"}]),
    ],
)
def test_extract_json_array_robust(raw: str, expected: object) -> None:
    assert _extract_json_from_text(raw, expect_array=True) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "No JSON here at all.",
        "Just prose with {unbalanced",
    ],
)
def test_extract_json_from_text_no_result(raw: str) -> None:
    assert _extract_json_from_text(raw, expect_array=False) is None


def test_object_schema_with_array_field_not_misread() -> None:
    """An object schema whose output contains an array field must not be
    misread as the embedded array (array-first ambiguity)."""
    raw = '{"name": "Alice", "items": [{"id": 1}]}'
    result = _extract_json_from_text(raw, expect_array=False)
    assert isinstance(result, dict)
    assert result["name"] == "Alice"
    assert result["items"] == [{"id": 1}]


def test_array_schema_ignores_prose_framing() -> None:
    raw = 'Result:\n[{"id": 1},]'
    result = _extract_json_from_text(raw, expect_array=True)
    assert result == [{"id": 1}]
