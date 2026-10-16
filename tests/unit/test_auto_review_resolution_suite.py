"""
[POS] tests/unit/test_auto_review_resolution_suite.py
[INPUT] myrm_agent_harness.core.security.auto_review_resolution, agent.middlewares.approval.denial_diagnostic_bridge
[OUTPUT] Unit test suite for the Auto-Review Denial diagnostic and the model-facing denial message built from it

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import gc
import re

import pytest

from myrm_agent_harness.agent.middlewares.approval.denial_diagnostic_bridge import (
    build_auto_review_denial_message,
    infer_denial_reason_code,
)
from myrm_agent_harness.core.security.auto_review_resolution import (
    DenialDiagnosticPayload,
    DenialDiagnosticReporter,
    DenialReasonCodeEnum,
    ResolutionBranchEnum,
)

_DIAGNOSTIC_ID = re.compile(r"Diagnostic ID: diag-[0-9a-f]{12}")


def _diagnostic_id(message: str) -> str:
    match = _DIAGNOSTIC_ID.search(message)
    assert match is not None, message
    return match.group()


def test_diagnostic_reporter_inference() -> None:
    """Test structured diagnostic generation with automated alternative inference."""
    # 1. High risk action defaults to HANDOVER_TO_USER
    diag_high = DenialDiagnosticReporter.generate_diagnostic(
        blocked_action="deploy_k8s_cluster",
        denial_reason="Direct production cluster mutation denied by policy.",
        reason_code=DenialReasonCodeEnum.HIGH_RISK_ACTION,
        policy_rule_id="RULE-PROD-01",
        context_data={"env": "production"},
    )
    assert diag_high.suggested_branch == ResolutionBranchEnum.HANDOVER_TO_USER
    assert len(diag_high.allowed_alternatives) > 0
    assert "generate staged dry-run diff preview" in diag_high.allowed_alternatives

    # 2. Unauthorized path defaults to TRY_ALTERNATIVE
    diag_path = DenialDiagnosticReporter.generate_diagnostic(
        blocked_action="write_etc_hosts",
        denial_reason="Modifying system file /etc/hosts is forbidden.",
        reason_code=DenialReasonCodeEnum.UNAUTHORIZED_PATH,
        policy_rule_id="RULE-PATH-02",
    )
    assert diag_path.suggested_branch == ResolutionBranchEnum.TRY_ALTERNATIVE
    assert any("patch" in alt for alt in diag_path.allowed_alternatives)

    # 3. Isolation breach defaults to STOP_OPERATION
    diag_breach = DenialDiagnosticReporter.generate_diagnostic(
        blocked_action="ptrace_attach",
        denial_reason="Sandbox breakout attempt detected.",
        reason_code=DenialReasonCodeEnum.SANDBOX_ISOLATION_BREACH,
        policy_rule_id="RULE-SEC-CRIT",
    )
    assert diag_breach.suggested_branch == ResolutionBranchEnum.STOP_OPERATION


@pytest.mark.parametrize(
    ("reason", "tool_name", "expected"),
    [
        ("Unauthorized path /etc/hosts", "file_write_tool", DenialReasonCodeEnum.UNAUTHORIZED_PATH),
        ("Credential egress blocked", "web_fetch_tool", DenialReasonCodeEnum.SENSITIVE_DATA_LEAK),
        ("Too many requests", "web_search_tool", DenialReasonCodeEnum.RATE_LIMIT_EXCEEDED),
        ("Sandbox escape attempt", "bash_code_execute_tool", DenialReasonCodeEnum.SANDBOX_ISOLATION_BREACH),
        ("Blocked by policy", "delete_everything", DenialReasonCodeEnum.HIGH_RISK_ACTION),
        ("Irreversible destructive command", "bash_code_execute_tool", DenialReasonCodeEnum.HIGH_RISK_ACTION),
        ("Blocked by policy", "file_write_tool", DenialReasonCodeEnum.POLICY_VIOLATION),
        # The first matching family wins: a path that also mentions a credential is a path denial.
        ("Credential file outside the allowed path", "file_read_tool", DenialReasonCodeEnum.UNAUTHORIZED_PATH),
    ],
)
def test_reason_code_follows_the_denial_text_and_the_tool(
    reason: str, tool_name: str, expected: DenialReasonCodeEnum
) -> None:
    assert infer_denial_reason_code(reason, tool_name) == expected


def test_denial_message_is_the_structured_text_the_model_reads() -> None:
    """Pins the exact model-facing wording, so a change to it is a deliberate edit and never a side effect."""
    reason = "Unauthorized path /etc/hosts"
    hint = "\n[HINT: stop retrying]"

    message = build_auto_review_denial_message("file_write_tool", reason, hint)

    assert message.replace(_diagnostic_id(message), "Diagnostic ID: <id>") == (
        "Tool execution denied by security policy: Unauthorized path /etc/hosts\n"
        "[HINT: stop retrying]\n"
        "\n"
        "[SECURITY_DENIAL_DIAGNOSTIC]\n"
        "Diagnostic ID: <id>\n"
        "Reason Code: UNAUTHORIZED_PATH\n"
        "Suggested Branch: TRY_ALTERNATIVE\n"
        "Allowed Alternatives:\n"
        "  - read-only file inspection via file_read\n"
        "  - create patch file in workspace instead of system directory\n"
        "  - ask user for elevated path grant\n"
        "\n"
        "Instruction: You must now adapt by choosing one of the four resolution branches:\n"
        "1. ASK_USER: Ask the user for explicit authorization or clarification.\n"
        "2. TRY_ALTERNATIVE: Attempt one of the allowed alternatives above.\n"
        "3. HANDOVER_TO_USER: Hand this specific operation over to the user for manual confirmation.\n"
        "4. STOP_OPERATION: Terminate the blocked trajectory safely and report findings to user."
    )


def test_every_denial_gets_its_own_diagnostic_id() -> None:
    ids = {_diagnostic_id(build_auto_review_denial_message("file_write_tool", "Blocked by policy")) for _ in range(50)}

    assert len(ids) == 50


def _live_diagnostics() -> int:
    gc.collect()
    return sum(1 for obj in gc.get_objects() if isinstance(obj, DenialDiagnosticPayload))


def test_denials_leave_no_per_denial_state_behind() -> None:
    """A long-lived process turns each denial into a message and keeps nothing, however many it sees."""
    before = _live_diagnostics()

    for run in range(500):
        build_auto_review_denial_message("bash_code_execute_tool", f"Irreversible destructive delete in run {run}")

    assert _live_diagnostics() == before
