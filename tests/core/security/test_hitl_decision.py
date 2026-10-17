"""Tests for the one reading of a human's HITL decision — every real client shape, and every denial shape."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.hitl_decision import (
    APPROVE_WORDS,
    is_approved,
    rejection_feedback,
)

DRAWER_APPROVE = {"decision": "approve"}
"""WebUI approval drawer: one decision for the whole pause (``buildDrawerResumeValue.ts``)."""
DRAWER_REJECT = {"decision": "reject", "feedback": "too expensive"}
IM_APPROVE = {"decisions": [{"type": "approve"}]}
"""IM channel buttons: the same batch shape the chat tool-approval card sends (``router_commands_approval.py``)."""
IM_REJECT = {"decisions": [{"type": "reject", "feedback": "Denied via feishu channel command"}]}
IM_DENY_WITH_REASON = {"decisions": [{"type": "reject", "guidance": "use the REST API instead"}]}
CHAT_TOOL_APPROVE = {"decisions": [{"type": "approve", "extensions": {"allowAlways": False}}]}
EDIT_APPROVE = {"decisions": [{"type": "edit", "args": {"command": "ls"}}]}


@pytest.mark.parametrize(
    "answer",
    [
        DRAWER_APPROVE,
        IM_APPROVE,
        {"decisions": [{"type": "approve"}, {"type": "approve"}]},
        CHAT_TOOL_APPROVE,
        {"decision": "edit"},
        EDIT_APPROVE,
        "approve",
        "ALLOW",
        "yes",
        "y",
    ],
)
def test_real_approval_shapes_are_approved(answer: object) -> None:
    assert is_approved(answer) is True


@pytest.mark.parametrize(
    "answer",
    [
        DRAWER_REJECT,
        IM_REJECT,
        {"decisions": [{"type": "reject"}]},
        {"decisions": [{"type": "approve"}, {"type": "reject"}]},
        {"decision": "reject"},
        {"decision": "deny"},
        "reject",
        "no",
        "deny",
    ],
)
def test_real_denial_shapes_deny(answer: object) -> None:
    assert is_approved(answer) is False


@pytest.mark.parametrize(
    "answer",
    [
        None,
        {},
        {"decisions": []},
        {"decisions": "approve"},
        {"decisions": [None]},
        {"decisions": ["approve"]},
        {"decisions": [{"type": 0}]},
        {"approved": True},
        {"approved": False},
        {"decision": True},
        {"decision": "APPROVED"},
        True,
        0,
        [],
        [{"approved": True}],
        "ok",
        "",
        {"status": "approve"},
    ],
)
def test_unrecognized_shapes_deny_fail_closed(answer: object) -> None:
    """A shape no client sends must never open a gate: an answer that cannot be read is a denial."""
    assert is_approved(answer) is False


def test_every_approve_word_is_a_lowercase_token() -> None:
    assert APPROVE_WORDS and all(word == word.lower() for word in APPROVE_WORDS)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (DRAWER_REJECT, "too expensive"),
        (IM_REJECT, "Denied via feishu channel command"),
        (IM_DENY_WITH_REASON, "use the REST API instead"),
        ({"decision": "reject", "guidance": "/deny slides the reason here"}, "/deny slides the reason here"),
        ({"decisions": [{"type": "reject"}, {"type": "reject", "feedback": "second reason"}]}, "second reason"),
        ({"decision": "reject"}, ""),
        (IM_APPROVE, ""),
        (None, ""),
        ("reject", ""),
    ],
)
def test_rejection_feedback_reads_the_human_words(answer: object, expected: str) -> None:
    assert rejection_feedback(answer) == expected
