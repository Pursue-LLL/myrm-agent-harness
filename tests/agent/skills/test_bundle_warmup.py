"""Unit tests for Skill Bundles Batch Manifest & Lifecycle Warmup Manager (Item 41).

[INPUT]
- myrm_agent_harness.agent.skills.bundle_warmup::{
    BundleActivationRecord,
    BundleCategory,
    BundleSkillSpec,
    BundleWarmupCheck,
    BundleWarmupReport,
    SkillBundleError,
    SkillBundleLifecycleManager,
    SkillBundleManifest,
    SkillBundleWarmupBlockedError,
    WarmupStatus,
  }

[OUTPUT]
- Pytest cases verifying scenario-based bundle registration, dependency pre-flight warmup,
  blocking thresholds, atomic session activation, and lifecycle deactivation.

[POS]
- myrm-agent-harness/tests/agent/skills/test_bundle_warmup.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.skills.bundle_warmup import (
    BundleCategory,
    BundleSkillSpec,
    SkillBundleError,
    SkillBundleLifecycleManager,
    SkillBundleManifest,
    SkillBundleWarmupBlockedError,
    WarmupStatus,
)


@pytest.fixture
def manager() -> SkillBundleLifecycleManager:
    return SkillBundleLifecycleManager(include_defaults=True)


def test_default_seeded_bundles(manager: SkillBundleLifecycleManager) -> None:
    bundles = manager.list_bundles()
    assert len(bundles) >= 3

    coding_bundle = manager.get_bundle("bundle_fullstack_coding")
    assert coding_bundle is not None
    assert coding_bundle.category == BundleCategory.CODING
    assert len(coding_bundle.skills) == 3

    wechat_bundle = manager.get_bundle("bundle_wechat_publisher")
    assert wechat_bundle is not None
    assert wechat_bundle.category == BundleCategory.WRITING

    finance_bundle = manager.get_bundle("bundle_finance_audit")
    assert finance_bundle is not None
    assert finance_bundle.category == BundleCategory.FINANCE


def test_register_and_get_bundle(manager: SkillBundleLifecycleManager) -> None:
    manifest = SkillBundleManifest(
        bundle_id="custom_security_pack",
        name="Zero-Trust Security Suite",
        description="Comprehensive SAST, DAST, and secret leakage scanner.",
        category=BundleCategory.SECURITY,
        skills=[
            BundleSkillSpec(
                skill_id="sast-analyzer",
                name="Static Analysis Tool",
                description="Checks code AST for common weaknesses.",
                required_env_vars=["SECURITY_TOKEN"],
            ),
        ],
        author="sec-team",
    )
    registered = manager.register_bundle(manifest)
    assert registered.bundle_id == "custom_security_pack"

    fetched = manager.get_bundle("custom_security_pack")
    assert fetched is not None
    assert fetched.name == "Zero-Trust Security Suite"

    # Validation errors
    with pytest.raises(SkillBundleError, match="Bundle ID cannot be blank"):
        manager.register_bundle(
            SkillBundleManifest(
                bundle_id="",
                name="Bad",
                description="Bad",
                category=BundleCategory.CUSTOM,
                skills=[BundleSkillSpec("s", "n", "d")],
            )
        )

    with pytest.raises(SkillBundleError, match="at least one skill"):
        manager.register_bundle(
            SkillBundleManifest(
                bundle_id="empty_bundle",
                name="Empty",
                description="Empty",
                category=BundleCategory.CUSTOM,
                skills=[],
            )
        )


def test_warmup_bundle_all_ready(manager: SkillBundleLifecycleManager) -> None:
    available_skills = {"code-refactor", "test-runner", "security-linter"}
    env_vars: dict[str, str] = {}

    report = manager.warmup_bundle(
        bundle_id="bundle_fullstack_coding",
        available_skills=available_skills,
        env_vars=env_vars,
    )

    assert report.bundle_id == "bundle_fullstack_coding"
    assert report.overall_status == WarmupStatus.READY
    assert all(c.status == WarmupStatus.READY for c in report.checks)


def test_warmup_bundle_blocked_missing_required_skill(
    manager: SkillBundleLifecycleManager,
) -> None:
    # Missing required 'code-refactor'
    available_skills = {"test-runner", "security-linter"}
    report = manager.warmup_bundle(
        bundle_id="bundle_fullstack_coding",
        available_skills=available_skills,
        env_vars={},
    )

    assert report.overall_status == WarmupStatus.BLOCKED
    blocked_checks = [c for c in report.checks if c.status == WarmupStatus.BLOCKED]
    assert len(blocked_checks) >= 1
    assert "code-refactor" in blocked_checks[0].message


def test_warmup_bundle_warning_optional_skill(
    manager: SkillBundleLifecycleManager,
) -> None:
    # Has required 'code-refactor' & 'test-runner', but missing optional 'security-linter'
    available_skills = {"code-refactor", "test-runner"}
    report = manager.warmup_bundle(
        bundle_id="bundle_fullstack_coding",
        available_skills=available_skills,
        env_vars={},
    )

    assert report.overall_status == WarmupStatus.WARNING
    warning_checks = [c for c in report.checks if c.status == WarmupStatus.WARNING]
    assert len(warning_checks) == 1
    assert "security-linter" in warning_checks[0].message


def test_warmup_bundle_blocked_missing_env_var(
    manager: SkillBundleLifecycleManager,
) -> None:
    available_skills = {
        "content-topic-generator",
        "wechat-publisher",
        "title-ab-tester",
    }
    # Missing required WECHAT_APP_SECRET
    report = manager.warmup_bundle(
        bundle_id="bundle_wechat_publisher",
        available_skills=available_skills,
        env_vars={},
    )

    assert report.overall_status == WarmupStatus.BLOCKED
    env_checks = [
        c
        for c in report.checks
        if "WECHAT_APP_SECRET" in c.check_name and c.status == WarmupStatus.BLOCKED
    ]
    assert len(env_checks) == 1

    # When env var provided, overall status becomes READY
    report_fixed = manager.warmup_bundle(
        bundle_id="bundle_wechat_publisher",
        available_skills=available_skills,
        env_vars={"WECHAT_APP_SECRET": "sec_abc123"},
    )
    assert report_fixed.overall_status == WarmupStatus.READY


def test_activate_bundle_success_and_deactivate(
    manager: SkillBundleLifecycleManager,
) -> None:
    session_id = "chat_sess_01"
    available_skills = {"excel-cleaner", "invoice-matcher"}

    record = manager.activate_bundle(
        session_id=session_id,
        bundle_id="bundle_finance_audit",
        available_skills=available_skills,
        env_vars={},
    )
    assert record.session_id == session_id
    assert record.bundle_id == "bundle_finance_audit"
    assert record.warmup_status == WarmupStatus.READY
    assert record.activated_skills == ["excel-cleaner", "invoice-matcher"]

    active = manager.get_session_activations(session_id)
    assert len(active) == 1
    assert active[0].bundle_id == "bundle_finance_audit"

    # Deactivate
    deactivated = manager.deactivate_bundle(session_id, "bundle_finance_audit")
    assert deactivated is True
    assert len(manager.get_session_activations(session_id)) == 0


def test_activate_bundle_blocked_error_and_force(
    manager: SkillBundleLifecycleManager,
) -> None:
    session_id = "chat_sess_blocked"
    # Missing required skills
    available_skills: set[str] = set()

    with pytest.raises(SkillBundleWarmupBlockedError, match="warmup blocked"):
        manager.activate_bundle(
            session_id=session_id,
            bundle_id="bundle_finance_audit",
            available_skills=available_skills,
            env_vars={},
            force=False,
        )

    # Force activation records the activation despite BLOCKED status
    forced_record = manager.activate_bundle(
        session_id=session_id,
        bundle_id="bundle_finance_audit",
        available_skills=available_skills,
        env_vars={},
        force=True,
    )
    assert forced_record.bundle_id == "bundle_finance_audit"
    assert forced_record.warmup_status == WarmupStatus.BLOCKED
    assert len(manager.get_session_activations(session_id)) == 1
