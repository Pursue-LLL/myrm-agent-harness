"""Tests for summary_auditor: quality gates for structured summaries."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.strategies.summary_auditor import (
    AuditResult,
    audit_summary,
    build_retry_guidance,
    extract_key_entities,
)

_DEFAULT_ACTIONS = ["Analyzed auth flow", "Updated jwt.py"]
_DEFAULT_FINDINGS = ["Token expiry was too short"]
_DEFAULT_FILES = ["app/core/security/auth/jwt.py"]


def _make_summary(
    *,
    user_goal: str = "Refactor the authentication module",
    completed_actions: list[str] | None = None,
    key_findings: list[str] | None = None,
    files_modified: list[str] | None = None,
    last_action: str = "Updated jwt.py with new token validation",
) -> StructuredSummary:
    return StructuredSummary(
        user_goal=user_goal,
        completed_actions=_DEFAULT_ACTIONS if completed_actions is None else completed_actions,
        key_findings=_DEFAULT_FINDINGS if key_findings is None else key_findings,
        files_modified=_DEFAULT_FILES if files_modified is None else files_modified,
        last_action=last_action,
    )


def _make_messages(texts: list[str]) -> list[HumanMessage]:
    return [HumanMessage(content=t) for t in texts]


class TestExtractKeyEntities:
    def test_extracts_file_paths(self):
        msgs = _make_messages(["Modified app/core/security/auth/jwt.py and utils/helpers.py"])
        entities = extract_key_entities(msgs)
        assert "app/core/security/auth/jwt.py" in entities
        assert "utils/helpers.py" in entities

    def test_extracts_identifiers(self):
        msgs = _make_messages(["def validate_token(token): ...\nclass AuthManager: ..."])
        entities = extract_key_entities(msgs)
        assert "validate_token" in entities
        assert "AuthManager" in entities

    def test_filters_noise(self):
        msgs = _make_messages(["def test(): return true"])
        entities = extract_key_entities(msgs)
        assert "test" not in entities
        assert "true" not in entities

    def test_empty_messages(self):
        entities = extract_key_entities([])
        assert entities == set()

    def test_non_string_content(self):
        msgs = [AIMessage(content=[{"type": "text", "text": "hello"}])]
        entities = extract_key_entities(msgs)
        assert isinstance(entities, set)


class TestAuditSummary:
    def test_good_summary_passes(self):
        summary = _make_summary(files_modified=["app/core/security/auth/jwt.py", "utils/helpers.py"])
        long_context = (
            "I need to refactor app/core/security/auth/jwt.py to improve token validation. "
            "The current implementation has several issues with token expiry handling. "
            "Also check utils/helpers.py for shared utility functions. "
            "def validate_token(token): checks the JWT signature and expiry. "
        ) * 20
        msgs = _make_messages([long_context])
        result = audit_summary(summary, msgs)
        assert result.passed
        assert result.entity_retained > 0

    def test_empty_goal_fails(self):
        summary = _make_summary(user_goal="")
        msgs = _make_messages(["some context"])
        result = audit_summary(summary, msgs)
        assert not result.passed
        assert any("user_goal" in i for i in result.issues)

    def test_empty_actions_fails(self):
        summary = _make_summary(completed_actions=[])
        long_context = "Working on the authentication module. " * 50
        msgs = _make_messages([long_context])
        result = audit_summary(summary, msgs)
        assert not result.passed
        assert any("completed_actions" in i for i in result.issues)

    def test_empty_last_action_fails(self):
        summary = _make_summary(last_action="")
        msgs = _make_messages(["some context"])
        result = audit_summary(summary, msgs)
        assert not result.passed
        assert any("last_action" in i for i in result.issues)

    def test_low_entity_retention_fails(self):
        summary = _make_summary(files_modified=[])
        msgs = _make_messages(
            [
                "Modified app/core/security/auth/jwt.py",
                "Updated utils/helpers.py",
                "Changed config/settings.py",
                "Fixed database/models.py",
                "Edited api/routes.py",
            ]
        )
        entities = extract_key_entities(msgs)
        assert len(entities) > 0

        result = audit_summary(summary, msgs, entities=entities)
        if result.entity_retained / len(entities) < 0.30:
            assert not result.passed
            assert any("retention" in i.lower() for i in result.issues)

    def test_precomputed_entities(self):
        summary = _make_summary()
        msgs = _make_messages(["some text"])
        custom_entities = {"jwt.py", "AuthManager", "validate_token"}
        result = audit_summary(summary, msgs, entities=custom_entities)
        assert result.entity_total == 3


class TestAuditResult:
    def test_retention_rate_with_entities(self):
        result = AuditResult(passed=True, entity_total=10, entity_retained=7)
        assert result.retention_rate == pytest.approx(0.7)

    def test_retention_rate_no_entities(self):
        result = AuditResult(passed=True, entity_total=0, entity_retained=0)
        assert result.retention_rate == 1.0


class TestBuildRetryGuidance:
    def test_includes_missing_entities(self):
        result = AuditResult(
            passed=False, issues=["Entity retention too low"], missing_entities=["jwt.py", "AuthManager"]
        )
        guidance = build_retry_guidance(result)
        assert "jwt.py" in guidance
        assert "AuthManager" in guidance

    def test_sparse_guidance(self):
        result = AuditResult(passed=False, issues=["Summary too sparse: 2% of original"])
        guidance = build_retry_guidance(result)
        assert "short" in guidance.lower() or "detail" in guidance.lower()

    def test_verbose_guidance(self):
        result = AuditResult(passed=False, issues=["Summary too verbose: 50% of original"])
        guidance = build_retry_guidance(result)
        assert "concise" in guidance.lower() or "long" in guidance.lower()

    def test_empty_issues_fallback(self):
        result = AuditResult(passed=False, issues=[])
        guidance = build_retry_guidance(result)
        assert len(guidance) > 0


class TestErrorsAndFixesEntityRetention:
    def test_entity_in_errors_and_fixes_counted(self):
        summary = _make_summary(files_modified=[])
        summary_with_errors = StructuredSummary(
            user_goal=summary.user_goal,
            completed_actions=summary.completed_actions,
            key_findings=summary.key_findings,
            errors_and_fixes=["app/core/security/auth/jwt.py import failed -> added __init__.py"],
            files_modified=[],
            last_action=summary.last_action,
        )
        entities = {"app/core/security/auth/jwt.py"}
        result = audit_summary(
            summary_with_errors, _make_messages(["Modified app/core/security/auth/jwt.py"]), entities=entities
        )
        assert result.entity_retained == 1
        assert result.entity_total == 1
