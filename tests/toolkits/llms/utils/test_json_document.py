"""is_json_document: the acceptance test reasoning text must pass to stand in for an empty answer."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.utils.json_document import is_json_document


@pytest.mark.parametrize(
    "text",
    [
        '{"answer": 42}',
        "[1, 2]",
        '  {"answer": 42}\n',
        'Final answer:\n```json\n{"answer": 42}\n```',
    ],
)
def test_accepts_json_object_or_array(text: str) -> None:
    assert is_json_document(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "no braces at all",
        "We need answer JSON only. Draft: { 'patterns': [ pick the strongest first",
        'The schema is {"patterns": [...]} so I will think about each memory in turn',
        'Answer: {"answer": 42}',
        "42",
        '"a string"',
    ],
)
def test_rejects_prose_and_json_scalars(text: str) -> None:
    assert is_json_document(text) is False
