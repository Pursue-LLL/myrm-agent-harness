"""Unit tests for SingleUseTicketManager and three-token chain content digest binding."""

from __future__ import annotations

import time

from myrm_agent_harness.agent.security.single_use_tickets import (
    SingleUseTicketManager,
    TicketStatus,
    TokenType,
    compute_content_digest,
)


def test_compute_content_digest_stable_and_sensitive_to_tampering() -> None:
    tool = "run_shell"
    args1 = {"command": "SELECT * FROM users WHERE id = 1;", "timeout": 30}
    args2 = {"timeout": 30, "command": "SELECT * FROM users WHERE id = 1;"}
    tampered_args = {"command": "DROP TABLE users;", "timeout": 30}

    # Dict key order invariance
    d1 = compute_content_digest(tool, args1)
    d2 = compute_content_digest(tool, args2)
    assert d1 == d2

    # Tampered command produces completely different digest
    d3 = compute_content_digest(tool, tampered_args)
    assert d1 != d3


def test_mint_verify_and_consume_atomic_lifecycle() -> None:
    manager = SingleUseTicketManager()
    session_id = "sess-ticket-1"
    tool_name = "run_shell"
    args = {"command": "mysql -u root -p"}

    ticket = manager.mint_ticket(
        session_id=session_id,
        token_type=TokenType.QUERY,
        tool_name=tool_name,
        args=args,
        ttl_seconds=30.0,
        bound_credential_handles=["cred_ephemeral_1234"],
    )

    assert ticket.ticket_id.startswith("ticket_quer_")
    assert ticket.status == TicketStatus.ISSUED
    assert ticket.is_active

    # Parameter tampering detection
    tampered_args = {"command": "rm -rf /"}
    success, reason, _ = manager.verify_and_consume(
        session_id, ticket.ticket_id, TokenType.QUERY, tool_name, tampered_args
    )
    assert not success
    assert "tampering or replay detected" in reason

    # Correct parameters: verification succeeds and atomically consumes
    success, reason, handles = manager.verify_and_consume(
        session_id, ticket.ticket_id, TokenType.QUERY, tool_name, args
    )
    assert success
    assert handles == ["cred_ephemeral_1234"]
    assert ticket.status == TicketStatus.CONSUMED

    # Replay attack: second consumption attempt fails immediately
    success, reason, _ = manager.verify_and_consume(
        session_id, ticket.ticket_id, TokenType.QUERY, tool_name, args
    )
    assert not success
    assert "already been consumed" in reason


def test_ticket_ttl_expiry_and_revocation() -> None:
    manager = SingleUseTicketManager()
    session_id = "sess-ticket-exp"
    args = {"action": "check"}

    ticket = manager.mint_ticket(
        session_id=session_id,
        token_type=TokenType.CONFIRMATION,
        tool_name="admin_tool",
        args=args,
        ttl_seconds=0.05,
    )

    time.sleep(0.06)
    success, reason, _ = manager.verify_and_consume(
        session_id, ticket.ticket_id, TokenType.CONFIRMATION, "admin_tool", args
    )
    assert not success
    assert "expired" in reason

    # Revocation test
    t2 = manager.mint_ticket(
        session_id=session_id,
        token_type=TokenType.EXPLORATION,
        tool_name="probe_tool",
        args=args,
        ttl_seconds=60.0,
    )
    assert manager.revoke_ticket(session_id, t2.ticket_id)
    success, reason, _ = manager.verify_and_consume(
        session_id, t2.ticket_id, TokenType.EXPLORATION, "probe_tool", args
    )
    assert not success
    assert "revoked" in reason
