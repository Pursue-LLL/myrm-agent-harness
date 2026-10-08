"""Unit tests for Untrusted Webhook Prompt Injection Defense and Toolset Demotion suite.

[POS]
Harness core security test suite verifying HMAC trust decoupling,
untrusted origin tool demotion, interactive admin approval cards, and post-approval unlock.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.webhook_guard import (
    ApprovalCardStatus,
    DemotedToolAccessDeniedError,
    OriginTaint,
    WebhookToolsetDemoter,
)


def test_filter_available_tools_tainted_vs_untainted() -> None:
    demoter = WebhookToolsetDemoter()
    all_tools = [
        "web_search",
        "web_extract",
        "file_read",
        "bash_code_execute",
        "file_write",
        "db_mutate",
    ]

    # 1. Untainted context (trusted internal scheduled job)
    clean_taint = OriginTaint(
        is_untrusted_external_content=False,
        origin_source="internal_cron",
        sender_identity="system_scheduler",
    )
    tools_clean = demoter.filter_available_tools(all_tools, clean_taint)
    assert tools_clean == all_tools

    # 2. Tainted context (external GitHub PR with potential prompt injection)
    untrusted_taint = OriginTaint(
        is_untrusted_external_content=True,
        origin_source="github_pr_comment",
        sender_identity="contributor_attacker",
    )
    tools_demoted = demoter.filter_available_tools(all_tools, untrusted_taint)
    assert "bash_code_execute" not in tools_demoted
    assert "file_write" not in tools_demoted
    assert "db_mutate" not in tools_demoted
    assert "web_search" in tools_demoted
    assert "file_read" in tools_demoted
    assert len(tools_demoted) == 3


def test_evaluate_execution_safe_vs_demoted() -> None:
    demoter = WebhookToolsetDemoter()
    task_id = "task_pr_review_42"

    untrusted_taint = OriginTaint(
        is_untrusted_external_content=True,
        origin_source="github_webhook",
        sender_identity="external_pr_author",
    )

    # 1. Safe tool succeeds
    allowed, card = demoter.evaluate_execution(
        task_id=task_id,
        tool_name="web_search",
        tool_args={"query": "python security best practices"},
        taint=untrusted_taint,
    )
    assert allowed is True
    assert card is None

    # 2. Dangerous tool raises DemotedToolAccessDeniedError and generates card
    with pytest.raises(DemotedToolAccessDeniedError) as exc_info:
        demoter.evaluate_execution(
            task_id=task_id,
            tool_name="bash_code_execute",
            tool_args={"command": "rm -rf / --no-preserve-root"},
            taint=untrusted_taint,
        )

    assert exc_info.value.tool_name == "bash_code_execute"
    assert exc_info.value.origin_source == "github_webhook"
    assert exc_info.value.card_id is not None

    # Check card registered in demoter
    generated_card = demoter.get_card(exc_info.value.card_id)
    assert generated_card is not None
    assert generated_card.status == ApprovalCardStatus.PENDING
    assert generated_card.task_id == task_id
    assert generated_card.requested_tool == "bash_code_execute"


def test_approval_card_workflow_and_post_approval_execution() -> None:
    demoter = WebhookToolsetDemoter()
    task_id = "task_ci_build_88"

    untrusted_taint = OriginTaint(
        is_untrusted_external_content=True,
        origin_source="gitlab_mr",
        sender_identity="external_dev",
    )

    # Trigger block
    card_id: str = ""
    try:
        demoter.evaluate_execution(
            task_id=task_id,
            tool_name="file_write",
            tool_args={"path": "dist/bundle.js", "content": "console.log(1)"},
            taint=untrusted_taint,
        )
    except DemotedToolAccessDeniedError as exc:
        card_id = exc.card_id or ""

    assert card_id != ""

    # Approve card by human admin
    approved_card = demoter.approve_card(card_id)
    assert approved_card.status == ApprovalCardStatus.APPROVED

    # Now tool execution is permitted
    allowed, card = demoter.evaluate_execution(
        task_id=task_id,
        tool_name="file_write",
        tool_args={"path": "dist/bundle.js", "content": "console.log(1)"},
        taint=untrusted_taint,
    )
    assert allowed is True
    assert card is not None
    assert card.card_id == card_id


def test_reject_approval_card() -> None:
    demoter = WebhookToolsetDemoter()
    task_id = "task_reject_01"

    untrusted_taint = OriginTaint(
        is_untrusted_external_content=True,
        origin_source="public_webhook",
        sender_identity="unknown_sender",
    )

    card_id: str = ""
    with pytest.raises(DemotedToolAccessDeniedError) as exc_info:
        demoter.evaluate_execution(
            task_id=task_id,
            tool_name="terminal_spawn",
            tool_args={"shell": "zsh"},
            taint=untrusted_taint,
        )
    card_id = exc_info.value.card_id or ""

    # Reject card
    rejected_card = demoter.reject_card(card_id)
    assert rejected_card.status == ApprovalCardStatus.REJECTED

    # Subsequent execution still blocked
    with pytest.raises(DemotedToolAccessDeniedError):
        demoter.evaluate_execution(
            task_id=task_id,
            tool_name="terminal_spawn",
            tool_args={"shell": "zsh"},
            taint=untrusted_taint,
        )
