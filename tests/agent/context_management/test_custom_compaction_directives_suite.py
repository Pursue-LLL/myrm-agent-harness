"""Unit tests for Custom Compaction Directives and Preservation Whitelist Suite.

Verifies custom directive parsing from markdown (e.g. CLAUDE.md), prompt slot injection,
post-compaction entity retention verification, and automatic self-healing patches.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    CompactionDirectivesInjector,
    CompactionIntegrityReport,
    CustomCompactionConfig,
    CustomCompactionDirectivesAndPreservationWhitelistSuite,
    DirectiveAuditResult,
    PreservationDirective,
    PreservationDirectiveKind,
    PreservationWhitelistAuditor,
)


def test_compaction_directives_injector_parsing_and_prompt_injection() -> None:
    """Verify parsing from markdown configuration blocks and prompt slot injection."""
    injector = CompactionDirectivesInjector()

    markdown_block = """
# Compact instructions
- Always preserve verbatim the latest test command and its output
- Retain critical database port '5432' and secret key 'JWT_SECRET'
- Keep architectural decision 'Use strict dataclasses without Any'
- Pending todo 'Refactor auth middleware'
"""
    directives = injector.parse_from_markdown_block(markdown_block)
    assert len(directives) == 4

    # Check classifications
    assert directives[0].kind == PreservationDirectiveKind.MUST_PRESERVE_VERBATIM
    assert directives[1].kind == PreservationDirectiveKind.PRESERVE_IDENTIFIER
    assert "5432" in directives[1].required_entities
    assert "JWT_SECRET" in directives[1].required_entities
    assert directives[2].kind == PreservationDirectiveKind.PRESERVE_DECISION
    assert directives[3].kind == PreservationDirectiveKind.PRESERVE_TODO

    # Prompt injection
    base_prompt = "You are a summarizer.\n\n## Conversation History\nUser: Hello"
    injected_prompt = injector.inject_into_prompt(base_prompt, directives)
    assert "## DOMAIN PRESERVATION DIRECTIVES (USER DEFINED" in injected_prompt
    assert "JWT_SECRET" in injected_prompt
    assert "5432" in injected_prompt
    assert injected_prompt.index("## DOMAIN PRESERVATION DIRECTIVES") < injected_prompt.index("## Conversation History")


def test_preservation_whitelist_auditor_verification_and_healing() -> None:
    """Verify auditing and self-healing when LLM summary omits critical domain entities."""
    auditor = PreservationWhitelistAuditor()

    directives = [
        PreservationDirective(
            directive_id="dir-01",
            kind=PreservationDirectiveKind.PRESERVE_IDENTIFIER,
            instruction="Retain database port and secret key",
            required_entities=["5432", "JWT_SECRET"],
        ),
        PreservationDirective(
            directive_id="dir-02",
            kind=PreservationDirectiveKind.PRESERVE_DECISION,
            instruction="Retain strict typing decision",
            required_entities=["ZeroAny"],
        ),
    ]

    raw_context = """
User: Please deploy the service on port 5432 with secret JWT_SECRET=sk-99881122.
Assistant: Configured PostgreSQL on 5432 with JWT_SECRET. Also confirmed ZeroAny policy.
"""

    # Scenario A: Summary already contains all entities (clean pass)
    good_summary = {
        "active_task": "Deployed service",
        "key_findings": ["Database on 5432", "JWT_SECRET configured", "Follows ZeroAny"],
    }
    _, report_good = auditor.audit_and_heal(
        generated_summary=good_summary,
        raw_context=raw_context,
        directives=directives,
    )
    assert report_good.was_healed is False
    assert report_good.retention_rate == 1.0
    assert report_good.satisfied_count == 2
    assert report_good.missing_count == 0

    # Scenario B: Summary omitted JWT_SECRET and 5432 (triggers self-healing)
    deficient_summary = {
        "active_task": "Deployed service",
        "key_findings": ["Follows ZeroAny"],
    }
    healed_summary, report_healed = auditor.audit_and_heal(
        generated_summary=deficient_summary,
        raw_context=raw_context,
        directives=directives,
        auto_heal=True,
    )
    assert report_healed.was_healed is True
    assert "5432" in report_healed.healed_entities
    assert "JWT_SECRET" in report_healed.healed_entities
    assert report_healed.retention_rate == 1.0

    # Verify that healed summary contains the recovered facts
    assert isinstance(healed_summary, dict)
    preserved_facts = healed_summary.get("custom_preserved_facts", [])
    assert any("5432" in str(f) for f in preserved_facts)
    assert any("JWT_SECRET" in str(f) for f in preserved_facts)


def test_custom_compaction_directives_suite_facade() -> None:
    """Verify master suite orchestration from markdown configuration to self-healed summary."""
    suite = CustomCompactionDirectivesAndPreservationWhitelistSuite()

    markdown_instructions = """
- Preserve database URL 'postgres://localhost:5432/myrm'
- Retain bug tracking ID 'BUG-404'
"""
    directives = suite.parse_directives_markdown(markdown_instructions)
    assert len(directives) == 2

    raw_dialogue = "Investigated crash for BUG-404 on postgres://localhost:5432/myrm database."
    omitted_summary_str = "Summary: Fixed system crash and verified database operations."

    final_summary, report = suite.audit_and_heal_summary(
        generated_summary=omitted_summary_str,
        raw_context=raw_dialogue,
        directives=directives,
        session_id="sess-corp-99",
    )

    assert report.was_healed is True
    assert "BUG-404" in str(final_summary)
    assert "postgres://localhost:5432/myrm" in str(final_summary)

    # Telemetry metrics
    metrics = suite.get_aggregate_telemetry()
    assert metrics["total_compactions_audited"] == 1
    assert metrics["compactions_self_healed"] == 1
    assert metrics["average_directives_retention_rate"] == 1.0
    assert metrics["perfect_retention_ratio"] == 1.0
