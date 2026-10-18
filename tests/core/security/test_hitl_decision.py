"""Tests for the one reading of a human's HITL decision — every real client shape, and every denial shape."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.hitl_decision import (
    APPROVE_WORDS,
    approval_guidance,
    is_approved,
    rejection_feedback,
)

DRAWER_APPROVE = {"decision": "approve"}
"""WebUI approval drawer: one decision for the whole pause (``buildDrawerResumeValue.ts``)."""
DRAWER_APPROVE_WITH_NOTE = {"decision": "approve", "guidance": "only staging, not prod"}
"""The same drawer answer with the person's note on the approval (``PolymorphicApprovalCard.tsx``)."""
TIMEOUT_AUTO_APPROVE = {"decision": "approve", "feedback": "Auto-approved: approval timeout (300s)"}
"""The HITL timer's own synthetic answer (``agent/middlewares/approval/scheduler.py``): not a person's words."""
DRAWER_REJECT = {"decision": "reject", "feedback": "too expensive"}
IM_APPROVE = {"decisions": [{"type": "approve"}]}
"""IM channel buttons: the same batch shape the chat tool-approval card sends (``router_commands_approval.py``)."""
IM_REJECT = {"decisions": [{"type": "reject", "feedback": "Denied via feishu channel command"}]}
IM_DENY_WITH_REASON = {
    "decisions": [
        {
            "type": "reject",
            "feedback": "Denied via feishu channel command",
            "guidance": "use the REST API instead",
        }
    ]
}
"""IM ``/deny <reason>``: the sender always adds its own generic ``feedback``, the human's words ride ``guidance``."""
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
        (
            {"decision": "reject", "feedback": "User rejected this action.", "guidance": "stop touching prod"},
            "stop touching prod",
        ),
        ({"decision": "reject", "guidance": "", "feedback": "the real reason"}, "the real reason"),
        ({"decision": "reject", "guidance": "  "}, ""),
        ({"decisions": [{"type": "reject"}, {"type": "reject", "feedback": "second reason"}]}, "second reason"),
        ({"decision": "reject"}, ""),
        (IM_APPROVE, ""),
        (None, ""),
        ("reject", ""),
    ],
)
def test_rejection_feedback_reads_the_human_words(answer: object, expected: str) -> None:
    assert rejection_feedback(answer) == expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        # Whitespace is not a reason: a blank ``guidance`` falls through to the real ``feedback``.
        ({"decision": "reject", "guidance": "  ", "feedback": "the real reason"}, "the real reason"),
        # Both blank: nothing to pass on, so the key is left out of the refusal entirely.
        ({"decision": "reject", "guidance": "  ", "feedback": "\t\n "}, ""),
        ({"decision": "reject", "feedback": "\n"}, ""),
        # A batch entry with no words falls through to the next entry that has some.
        (
            {"decisions": [{"type": "reject", "feedback": "   "}, {"type": "reject", "feedback": "second reason"}]},
            "second reason",
        ),
        # Surrounding whitespace never reaches the model.
        ({"decision": "reject", "feedback": "  split it in two  "}, "split it in two"),
        ({"decision": "reject", "guidance": "\tuse the REST API\n"}, "use the REST API"),
    ],
)
def test_whitespace_only_feedback_is_not_a_reason(answer: object, expected: str) -> None:
    """A gate writes the field only when there is a reason; a blank string is not one."""
    assert rejection_feedback(answer) == expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (DRAWER_APPROVE_WITH_NOTE, "only staging, not prod"),
        # A batch answer carries the note on its first approving entry.
        (
            {"decisions": [{"type": "approve", "guidance": "use the staging URL"}]},
            "use the staging URL",
        ),
        ({"decisions": [{"type": "approve", "feedback": "ok"}, {"type": "approve", "guidance": "then rerun"}]}, "then rerun"),
        # Surrounding whitespace never reaches the model.
        ({"decision": "approve", "guidance": "  keep it under 10 USD  "}, "keep it under 10 USD"),
        # Blank, missing, and non-string notes are not notes.
        ({"decision": "approve", "guidance": "   "}, ""),
        ({"decision": "approve", "guidance": ""}, ""),
        ({"decision": "approve", "guidance": 42}, ""),
        (DRAWER_APPROVE, ""),
        ({"decision": "approve"}, ""),
        ({"decisions": [{"type": "approve"}]}, ""),
        (None, ""),
        ("approve", ""),
    ],
)
def test_approval_guidance_reads_the_humans_note_on_an_approval(answer: object, expected: str) -> None:
    """Only a note the person wrote counts; a blank or absent one is no note at all."""
    assert approval_guidance(answer) == expected


@pytest.mark.parametrize(
    "answer",
    [
        TIMEOUT_AUTO_APPROVE,
        {"decision": "approve", "feedback": "Auto-approved: approval timeout (300s)"},
        {"decisions": [{"type": "approve", "feedback": "Batch rejected by user"}]},
        {"decision": "approve", "feedback": "User rejected this action."},
    ],
)
def test_approval_guidance_never_reads_feedback(answer: object) -> None:
    """``feedback`` on an approval is a machine's own line, never the person's note.

    The HITL timer resumes a timed-out approval with
    ``feedback="Auto-approved: approval timeout (Ns)"`` and the batch buttons send their own
    labels; reading ``feedback`` here would feed those synthetic lines to the model as if the
    person had typed them. On a rejection ``feedback`` is the person's own reason, which
    ``rejection_feedback`` already reads — so a note on an approval comes only from ``guidance``.
    """
    assert approval_guidance(answer) == ""
