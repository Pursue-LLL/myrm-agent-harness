"""BashInput reason validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from myrm_agent_harness.agent.meta_tools.bash.bash_tool_helpers import BashInput


def test_reason_requires_minimum_length() -> None:
    with pytest.raises(ValidationError):
        BashInput(reason="short", command="echo hi")


def test_reason_accepts_valid_intent() -> None:
    model = BashInput(reason="List workspace files for review", command="ls -la")
    assert model.reason == "List workspace files for review"
