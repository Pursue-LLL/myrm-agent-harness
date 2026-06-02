"""Tests for memory conflict resolution mechanisms.

Validates the 6-layer conflict resolution system that covers all 5 competitor strategies:
- keep_new: CONTRADICTED_BY/SUPERSEDED_BY auto-downgrade
- keep_old: User governance (pinned facets survive)
- merge: Claim Graph compiles supporting evidence
- scope_split: CONSTRAINED_BY + namespace isolation
- skip: SUPPORTED_BY (no conflict)
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import (
    _classify_claim_relation,
    _contains_hint,
    _normalize_change_kind,
    _token_overlap,
)


class TestClassifyClaimRelation:
    """Tests for claim relationship classification (Claim Graph layer)."""

    def test_explicit_support(self) -> None:
        rel, downgrade = _classify_claim_relation(
            existing_goal="improve code quality",
            existing_result="use type hints everywhere",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="improve code quality",
            new_result="type annotations help",
            new_key_details="",
            new_polarity="positive",
            existing_evidence_count=3,
            explicit_change_kind="support",
        )
        assert rel == "SUPPORTED_BY"
        assert downgrade is False

    def test_explicit_contradict(self) -> None:
        rel, downgrade = _classify_claim_relation(
            existing_goal="language preference",
            existing_result="Python is best",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="language preference",
            new_result="Rust is better",
            new_key_details="",
            new_polarity="positive",
            existing_evidence_count=2,
            explicit_change_kind="contradict",
        )
        assert rel == "CONTRADICTED_BY"
        assert downgrade is True

    def test_explicit_supersede(self) -> None:
        rel, downgrade = _classify_claim_relation(
            existing_goal="deployment target",
            existing_result="using Heroku",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="deployment target",
            new_result="migrated to AWS",
            new_key_details="migrated",
            new_polarity="positive",
            existing_evidence_count=5,
            explicit_change_kind="supersede",
        )
        assert rel == "SUPERSEDED_BY"
        assert downgrade is True

    def test_explicit_constrain(self) -> None:
        rel, downgrade = _classify_claim_relation(
            existing_goal="database choice",
            existing_result="use PostgreSQL",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="database choice",
            new_result="only when data is relational",
            new_key_details="only when",
            new_polarity="positive",
            existing_evidence_count=3,
            explicit_change_kind="constrain",
        )
        assert rel == "CONSTRAINED_BY"
        assert downgrade is False

    def test_polarity_contradiction(self) -> None:
        """Opposite polarity signals contradiction without explicit change_kind."""
        rel, downgrade = _classify_claim_relation(
            existing_goal="testing approach",
            existing_result="unit tests are essential",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="testing approach",
            new_result="unit tests are waste of time",
            new_key_details="",
            new_polarity="negative",
            existing_evidence_count=4,
            explicit_change_kind="none",
        )
        assert rel == "CONTRADICTED_BY"
        assert downgrade is True

    def test_goal_overlap_with_supersede_hint(self) -> None:
        """High goal overlap + supersede hints → SUPERSEDED_BY."""
        rel, downgrade = _classify_claim_relation(
            existing_goal="preferred editor for development",
            existing_result="VSCode",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="preferred editor for development",
            new_result="switched to Cursor",
            new_key_details="switched",
            new_polarity="positive",
            existing_evidence_count=2,
            explicit_change_kind="none",
        )
        assert rel == "SUPERSEDED_BY"
        assert downgrade is True

    def test_goal_overlap_with_constraint_hint(self) -> None:
        """High goal overlap + constraint hints → CONSTRAINED_BY."""
        rel, downgrade = _classify_claim_relation(
            existing_goal="coding style preferences",
            existing_result="use functional programming",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="coding style preferences",
            new_result="only if the language supports it well",
            new_key_details="only if",
            new_polarity="positive",
            existing_evidence_count=3,
            explicit_change_kind="none",
        )
        assert rel == "CONSTRAINED_BY"
        assert downgrade is False

    def test_high_goal_overlap_low_result_overlap_contradiction(self) -> None:
        """High goal overlap + very low result overlap → CONTRADICTED_BY."""
        rel, downgrade = _classify_claim_relation(
            existing_goal="favorite programming language for backend",
            existing_result="Java with Spring Boot",
            existing_key_details="enterprise",
            existing_polarity="positive",
            new_goal="favorite programming language for backend",
            new_result="Go with minimal frameworks",
            new_key_details="simplicity",
            new_polarity="positive",
            existing_evidence_count=2,
            explicit_change_kind="none",
        )
        assert rel == "CONTRADICTED_BY"
        assert downgrade is True

    def test_no_existing_evidence_always_supported(self) -> None:
        """First evidence for a claim is always SUPPORTED_BY."""
        rel, downgrade = _classify_claim_relation(
            existing_goal="anything",
            existing_result="anything",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="totally different",
            new_result="completely unrelated",
            new_key_details="",
            new_polarity="negative",
            existing_evidence_count=0,
            explicit_change_kind="contradict",
        )
        assert rel == "SUPPORTED_BY"
        assert downgrade is False

    def test_different_goals_no_conflict(self) -> None:
        """Unrelated goals → SUPPORTED_BY (no relationship to conflict)."""
        rel, downgrade = _classify_claim_relation(
            existing_goal="frontend framework",
            existing_result="React",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="database choice",
            new_result="PostgreSQL",
            new_key_details="",
            new_polarity="positive",
            existing_evidence_count=5,
            explicit_change_kind="none",
        )
        assert rel == "SUPPORTED_BY"
        assert downgrade is False

    def test_change_kind_alias_replaced(self) -> None:
        """'replaced' is alias for supersede."""
        rel, downgrade = _classify_claim_relation(
            existing_goal="CI system",
            existing_result="Jenkins",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="CI system",
            new_result="GitHub Actions",
            new_key_details="",
            new_polarity="positive",
            existing_evidence_count=3,
            explicit_change_kind="replaced",
        )
        assert rel == "SUPERSEDED_BY"
        assert downgrade is True

    def test_change_kind_alias_conflict(self) -> None:
        """'conflict' is alias for contradict."""
        rel, downgrade = _classify_claim_relation(
            existing_goal="API style",
            existing_result="REST",
            existing_key_details="",
            existing_polarity="positive",
            new_goal="API style",
            new_result="GraphQL",
            new_key_details="",
            new_polarity="positive",
            existing_evidence_count=2,
            explicit_change_kind="conflict",
        )
        assert rel == "CONTRADICTED_BY"
        assert downgrade is True


class TestNormalizeChangeKind:
    """Tests for change_kind normalization with aliases."""

    @pytest.mark.parametrize(
        ("input_kind", "expected"),
        [
            ("support", "support"),
            ("supported", "support"),
            ("confirm", "support"),
            ("confirmed", "support"),
            ("contradict", "contradict"),
            ("contradicted", "contradict"),
            ("conflict", "contradict"),
            ("supersede", "supersede"),
            ("superseded", "supersede"),
            ("replace", "supersede"),
            ("replaced", "supersede"),
            ("migrate", "supersede"),
            ("migrated", "supersede"),
            ("constrain", "constrain"),
            ("constrained", "constrain"),
            ("constraint", "constrain"),
            ("none", "none"),
            ("unknown_value", "none"),
            ("", "none"),
            ("  SUPPORT  ", "support"),
        ],
    )
    def test_aliases(self, input_kind: str, expected: str) -> None:
        assert _normalize_change_kind(input_kind) == expected


class TestTokenOverlap:
    """Tests for token-based overlap calculation."""

    def test_identical_strings(self) -> None:
        assert _token_overlap("hello world", "hello world") == 1.0

    def test_no_overlap(self) -> None:
        assert _token_overlap("python java", "rust go") == 0.0

    def test_partial_overlap(self) -> None:
        overlap = _token_overlap("I like Python for backend", "I like Rust for backend")
        assert 0.5 < overlap < 0.9

    def test_empty_strings(self) -> None:
        assert _token_overlap("", "hello") == 0.0
        assert _token_overlap("hello", "") == 0.0
        assert _token_overlap("", "") == 0.0


class TestContainsHint:
    """Tests for hint detection in text."""

    def test_supersede_hints(self) -> None:
        from myrm_agent_harness.toolkits.memory._internal.maintenance import (
            _SUPERSEDE_HINTS,
        )

        assert _contains_hint("I switched to Rust", _SUPERSEDE_HINTS) is True
        assert _contains_hint("migrated the database", _SUPERSEDE_HINTS) is True
        assert _contains_hint("I still use Python", _SUPERSEDE_HINTS) is False

    def test_constraint_hints(self) -> None:
        from myrm_agent_harness.toolkits.memory._internal.maintenance import (
            _CONSTRAINT_HINTS,
        )

        assert _contains_hint("only if running on Linux", _CONSTRAINT_HINTS) is True
        assert _contains_hint("requires authentication", _CONSTRAINT_HINTS) is True
        assert _contains_hint("always use this tool", _CONSTRAINT_HINTS) is False
