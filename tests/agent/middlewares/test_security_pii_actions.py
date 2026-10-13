"""apply_pii_actions: one rewrite, with or without an audit trail.

The guard applies the policy to earlier user messages on every model call. Those rewrites repeat what was recorded
when the message was new, so they must not add audit entries, log lines or metrics a second time.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from myrm_agent_harness.agent.middlewares._session_context import set_pseudonym_store
from myrm_agent_harness.agent.middlewares.security.pii_actions import apply_pii_actions
from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SensitivityLevel
from myrm_agent_harness.core.security.audit import get_audit_entries, reset_audit_log

TEXT = "call 13812345678 please"
LEVELS = [SensitivityLevel.S2]


@pytest.fixture(autouse=True)
def _clean_session() -> Iterator[None]:
    reset_audit_log()
    set_pseudonym_store(None)
    yield
    set_pseudonym_store(None)


def _policy(action: PIIAction) -> PrivacyPolicy:
    return PrivacyPolicy(enabled=True, s2_action=action, s3_action=action)


class TestSilentMode:
    @pytest.mark.parametrize("action", [PIIAction.REDACT, PIIAction.PSEUDONYMIZE], ids=["redact", "pseudonymize"])
    def test_the_text_is_the_same_with_and_without_audit(self, action: PIIAction, tmp_path: Path) -> None:
        store = PseudonymStore(str(tmp_path / "ps.db"))
        set_pseudonym_store(store)

        audited = apply_pii_actions(TEXT, LEVELS, _policy(action), "user_input")
        silent = apply_pii_actions(TEXT, LEVELS, _policy(action), "user_input", audit=False)

        assert silent == audited
        assert silent is not None
        assert "13812345678" not in silent
        store.close()

    @pytest.mark.parametrize(
        "action", [PIIAction.REDACT, PIIAction.PSEUDONYMIZE], ids=["redact", "pseudonymize-fallback"]
    )
    def test_a_silent_rewrite_leaves_no_audit_entry_and_no_log_line(
        self, action: PIIAction, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            apply_pii_actions(TEXT, LEVELS, _policy(action), "user_input", audit=False)

        assert get_audit_entries() == []
        assert not [record for record in caplog.records if "[PII]" in record.getMessage()]

    @pytest.mark.parametrize(
        "action", [PIIAction.REDACT, PIIAction.PSEUDONYMIZE], ids=["redact", "pseudonymize-fallback"]
    )
    def test_an_audited_rewrite_leaves_both(self, action: PIIAction, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            apply_pii_actions(TEXT, LEVELS, _policy(action), "user_input")

        assert len(get_audit_entries()) == 1
        assert [record for record in caplog.records if "[PII]" in record.getMessage()]

    def test_the_pseudonym_is_audited_only_when_asked(self, tmp_path: Path) -> None:
        store = PseudonymStore(str(tmp_path / "ps.db"))
        set_pseudonym_store(store)

        apply_pii_actions(TEXT, LEVELS, _policy(PIIAction.PSEUDONYMIZE), "user_input", audit=False)
        assert get_audit_entries() == []

        apply_pii_actions(TEXT, LEVELS, _policy(PIIAction.PSEUDONYMIZE), "user_input")
        assert [entry.decision for entry in get_audit_entries()] == ["PII_PSEUDONYMIZED"]
        store.close()

    def test_a_block_is_the_same_with_and_without_audit(self) -> None:
        assert apply_pii_actions(TEXT, LEVELS, _policy(PIIAction.BLOCK), "user_input") is None
        assert apply_pii_actions(TEXT, LEVELS, _policy(PIIAction.BLOCK), "user_input", audit=False) is None
