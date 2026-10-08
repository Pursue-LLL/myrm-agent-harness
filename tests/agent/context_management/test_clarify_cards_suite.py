# [INPUT]: None
# [OUTPUT]: None
# [POS]: tests/agent/context_management/test_clarify_cards_suite.py

"""Comprehensive unit test suite for Hermes Desktop clarification cards."""

import time
import pytest

from myrm_agent_harness.agent.context_management.clarify_cards import (
    ClarifyCardPayload,
    ClarifyCardStatus,
    ClarifyOptionItem,
    ClarifyResponsePath,
    HermesDesktopClarifyCardsSuite,
    create_clarify_card,
)


def test_render_and_answer_clarification_card() -> None:
    """Validate render registration, supersede expiration, and answering lifecycle."""
    suite = HermesDesktopClarifyCardsSuite()

    # 1. Render first card
    card1, receipt1 = suite.render_clarification(
        question="Which database engine do you prefer?",
        session_id="sess_101",
        connection_id="conn_1",
        options=(
            ClarifyOptionItem("PostgreSQL", "postgres", "Recommended relational DB"),
            ClarifyOptionItem("SQLite", "sqlite", "Local embedded DB"),
        ),
        response_path=ClarifyResponsePath.DASHBOARD,
    )
    assert card1.status == ClarifyCardStatus.PENDING
    assert receipt1.action == "render"
    assert suite.get_active_card("sess_101") == card1

    # 2. Render a second card in the same session - card1 must be superseded and expired
    card2, receipt2 = suite.render_clarification(
        question="Which cloud deployment target?",
        session_id="sess_101",
        connection_id="conn_1",
        options=(ClarifyOptionItem("AWS", "aws"), ClarifyOptionItem("GCP", "gcp")),
    )
    assert card2.status == ClarifyCardStatus.PENDING
    assert suite.get_card(card1.request_id).status == ClarifyCardStatus.EXPIRED
    assert suite.get_active_card("sess_101") == card2

    # 3. Answer active card2
    answered_card2, answer_receipt = suite.answer_clarification(
        request_id=card2.request_id,
        answer="aws",
        session_id="sess_101",
        connection_id="conn_1",
    )
    assert answered_card2.status == ClarifyCardStatus.ANSWERED
    assert answered_card2.user_answer == "aws"
    assert answered_card2.resolved_at is not None
    assert answer_receipt.action == "answer"
    assert answer_receipt.status == ClarifyCardStatus.ANSWERED

    # No pending card left in session
    assert suite.get_active_card("sess_101") is None


def test_user_input_interception_prioritizes_clarify() -> None:
    """Ensure user chat input prioritizes answering active clarify cards before normal routing."""
    suite = HermesDesktopClarifyCardsSuite()

    # 1. When no pending clarify card exists, input passes through
    intercepted, card, receipt = suite.intercept_user_input(
        text="Hello world!",
        session_id="sess_202",
        connection_id="conn_2",
    )
    assert intercepted is False
    assert card is None
    assert receipt is None

    # 2. Render a clarify card
    suite.render_clarification(
        question="Do you want to enable debug logging?",
        session_id="sess_202",
        connection_id="conn_2",
        options=(ClarifyOptionItem("Yes", "yes"), ClarifyOptionItem("No", "no")),
    )

    # 3. Next chat input should be intercepted and treated as the answer
    intercepted, answered_card, receipt = suite.intercept_user_input(
        text="yes",
        session_id="sess_202",
        connection_id="conn_2",
    )
    assert intercepted is True
    assert answered_card is not None
    assert answered_card.status == ClarifyCardStatus.ANSWERED
    assert answered_card.user_answer == "yes"
    assert receipt is not None
    assert receipt.action == "answer"

    # 4. Subsequent input is no longer intercepted
    intercepted2, _, _ = suite.intercept_user_input(
        text="Continue running the migration",
        session_id="sess_202",
        connection_id="conn_2",
    )
    assert intercepted2 is False


def test_timeout_expiration_and_forbid_answer() -> None:
    """Validate auto-timeout detection and strict rejection of answering expired cards."""
    suite = HermesDesktopClarifyCardsSuite()

    # 1. Render card with tiny timeout
    card, _ = suite.render_clarification(
        question="Quick question?",
        session_id="sess_303",
        connection_id="conn_3",
        timeout_seconds=0.05,
    )

    # Sleep slightly past timeout
    time.sleep(0.08)

    # 2. get_active_card should detect timeout and transition card to EXPIRED
    active = suite.get_active_card("sess_303")
    assert active is None

    expired_card = suite.get_card(card.request_id)
    assert expired_card is not None
    assert expired_card.status == ClarifyCardStatus.EXPIRED

    # 3. Attempting to answer expired card must raise TimeoutError or ValueError
    with pytest.raises(ValueError):
        suite.answer_clarification(
            request_id=card.request_id,
            answer="Too late answer",
            session_id="sess_303",
            connection_id="conn_3",
        )


def test_connection_invalidation_and_option_validation() -> None:
    """Validate connection reset invalidation and closed options enforcement."""
    suite = HermesDesktopClarifyCardsSuite()

    # 1. Render card with closed options (allow_custom_input=False)
    card, _ = suite.render_clarification(
        question="Select an environment",
        session_id="sess_404",
        connection_id="conn_old",
        options=(
            ClarifyOptionItem("Production", "prod"),
            ClarifyOptionItem("Staging", "staging"),
        ),
        allow_custom_input=False,
    )

    # Invalid option value rejection
    with pytest.raises(ValueError, match="not a valid choice"):
        suite.answer_clarification(
            request_id=card.request_id,
            answer="invalid_env",
            session_id="sess_404",
            connection_id="conn_old",
        )

    # 2. Connection reset occurs -> invalidate pending card
    invalidated_cards = suite.invalidate_connection(
        session_id="sess_404",
        old_connection_id="conn_old",
    )
    assert len(invalidated_cards) == 1
    assert invalidated_cards[0].status == ClarifyCardStatus.INVALIDATED

    # 3. Answering with old connection must reject because card is invalidated
    with pytest.raises(ValueError, match="Cannot answer clarify card in status 'invalidated'"):
        suite.answer_clarification(
            request_id=card.request_id,
            answer="prod",
            session_id="sess_404",
            connection_id="conn_old",
        )

    # 4. Answering with new connection must reject due to connection mismatch
    with pytest.raises(ValueError, match="Connection ID mismatch"):
        suite.answer_clarification(
            request_id=card.request_id,
            answer="prod",
            session_id="sess_404",
            connection_id="conn_new",
        )

    # Interception on new connection must not touch invalidated card
    intercepted, _, _ = suite.intercept_user_input(
        text="prod",
        session_id="sess_404",
        connection_id="conn_new",
    )
    assert intercepted is False
