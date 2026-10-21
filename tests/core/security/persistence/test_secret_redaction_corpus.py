"""Corpus gate for secret redaction at the persistence boundary.

Both directions are pinned: every labeled secret must be gone (the label and prose around it kept), and no benign
text may change. Redaction is idempotent, because persisted text is scanned again (consolidation, restore).
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.persistence.content_scan import PersistScanProfile, scan_persistable_content

from .fixtures_secret_redaction import NEGATIVES, POSITIVES, Negative, Positive


def _clean(text: str) -> str:
    return scan_persistable_content(text, profile=PersistScanProfile.MEMORY_WRITE, pseudonymize=False).cleaned_text


@pytest.mark.parametrize("case", POSITIVES, ids=[case.id for case in POSITIVES])
def test_secrets_are_redacted_and_their_surroundings_kept(case: Positive) -> None:
    cleaned = _clean(case.text)

    assert [secret for secret in case.secrets if secret in cleaned] == []
    assert [fragment for fragment in case.kept if fragment not in cleaned] == []


@pytest.mark.parametrize("case", NEGATIVES, ids=[case.id for case in NEGATIVES])
def test_benign_text_is_not_altered(case: Negative) -> None:
    assert _clean(case.text) == case.text


@pytest.mark.parametrize("case", POSITIVES, ids=[case.id for case in POSITIVES])
def test_redaction_is_idempotent(case: Positive) -> None:
    once = _clean(case.text)

    assert _clean(once) == once
