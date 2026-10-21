"""Skill Bundle Lifecycle & Pre-flight Warmup Manager (Item 41).

[INPUT]
- SkillBundleManifest definitions, available skills inventory, runtime environment
  variables, and session activation requests.

[OUTPUT]
- Diagnostic pre-flight warmup reports, overall readiness verdicts, and session-scoped
  activation records.

[POS]
- Harness skills management engine implementing batch manifest packaging and warmup checks.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .types import (
    BundleActivationRecord,
    BundleCategory,
    BundleSkillSpec,
    BundleWarmupCheck,
    BundleWarmupReport,
    SkillBundleManifest,
    WarmupStatus,
)

logger = logging.getLogger(__name__)


class SkillBundleError(ValueError):
    """Base exception for skill bundle operations."""


class SkillBundleWarmupBlockedError(SkillBundleError):
    """Raised when bundle activation is attempted while warmup is in BLOCKED status."""


class SkillBundleLifecycleManager:
    """Manages batch manifest packaging, dependency warmup probes, and atomic activation."""

    def __init__(self, include_defaults: bool = True) -> None:
        self._bundles: dict[str, SkillBundleManifest] = {}
        self._session_activations: dict[str, list[BundleActivationRecord]] = {}

        if include_defaults:
            self._seed_default_bundles()

    def register_bundle(self, manifest: SkillBundleManifest) -> SkillBundleManifest:
        """Register or update a scenario-based skill bundle manifest."""
        if not manifest.bundle_id.strip():
            msg = "Bundle ID cannot be blank."
            raise SkillBundleError(msg)
        if not manifest.name.strip():
            msg = "Bundle name cannot be blank."
            raise SkillBundleError(msg)
        if not manifest.skills:
            msg = "A skill bundle must contain at least one skill specification."
            raise SkillBundleError(msg)

        self._bundles[manifest.bundle_id] = manifest
        logger.info("Registered skill bundle manifest '%s' (%s)", manifest.bundle_id, manifest.name)
        return manifest

    def get_bundle(self, bundle_id: str) -> SkillBundleManifest | None:
        """Retrieve a registered bundle manifest by bundle ID."""
        return self._bundles.get(bundle_id)

    def list_bundles(
        self, category: BundleCategory | None = None
    ) -> list[SkillBundleManifest]:
        """List registered bundles, optionally filtered by vertical category."""
        bundles = list(self._bundles.values())
        if category is not None:
            return [b for b in bundles if b.category == category]
        return bundles

    def warmup_bundle(
        self,
        bundle_id: str,
        available_skills: set[str],
        env_vars: dict[str, str],
        available_tools: set[str] | None = None,
    ) -> BundleWarmupReport:
        """Perform diagnostic pre-flight warmup checks on bundle dependencies."""
        bundle = self._require_bundle(bundle_id)
        checks: list[BundleWarmupCheck] = []
        has_blocked = False
        has_warning = False

        for skill in bundle.skills:
            # 1. Check skill existence
            if skill.skill_id in available_skills:
                checks.append(
                    BundleWarmupCheck(
                        check_name=f"skill_availability:{skill.skill_id}",
                        status=WarmupStatus.READY,
                        message=f"Skill '{skill.skill_id}' is available in system registry.",
                        is_resolved=True,
                    )
                )
            elif skill.is_optional:
                checks.append(
                    BundleWarmupCheck(
                        check_name=f"skill_availability:{skill.skill_id}",
                        status=WarmupStatus.WARNING,
                        message=f"Optional skill '{skill.skill_id}' is not installed.",
                        is_resolved=False,
                    )
                )
                has_warning = True
            else:
                checks.append(
                    BundleWarmupCheck(
                        check_name=f"skill_availability:{skill.skill_id}",
                        status=WarmupStatus.BLOCKED,
                        message=f"Required skill '{skill.skill_id}' is missing from system.",
                        is_resolved=False,
                    )
                )
                has_blocked = True

            # 2. Check required environment variables
            for env_var in skill.required_env_vars:
                if env_var in env_vars and env_vars[env_var].strip():
                    checks.append(
                        BundleWarmupCheck(
                            check_name=f"env_var:{skill.skill_id}:{env_var}",
                            status=WarmupStatus.READY,
                            message=f"Environment variable '{env_var}' is configured.",
                            is_resolved=True,
                        )
                    )
                elif skill.is_optional:
                    checks.append(
                        BundleWarmupCheck(
                            check_name=f"env_var:{skill.skill_id}:{env_var}",
                            status=WarmupStatus.WARNING,
                            message=f"Optional env var '{env_var}' missing for skill '{skill.skill_id}'.",
                            is_resolved=False,
                        )
                    )
                    has_warning = True
                else:
                    checks.append(
                        BundleWarmupCheck(
                            check_name=f"env_var:{skill.skill_id}:{env_var}",
                            status=WarmupStatus.BLOCKED,
                            message=f"Required env var '{env_var}' missing for skill '{skill.skill_id}'.",
                            is_resolved=False,
                        )
                    )
                    has_blocked = True

            # 3. Check required tools if tool catalog provided
            if available_tools is not None:
                for tool in skill.required_tools:
                    if tool in available_tools:
                        checks.append(
                            BundleWarmupCheck(
                                check_name=f"tool_availability:{skill.skill_id}:{tool}",
                                status=WarmupStatus.READY,
                                message=f"Required tool '{tool}' is mounted and active.",
                                is_resolved=True,
                            )
                        )
                    else:
                        checks.append(
                            BundleWarmupCheck(
                                check_name=f"tool_availability:{skill.skill_id}:{tool}",
                                status=WarmupStatus.BLOCKED,
                                message=f"Required tool '{tool}' is not available.",
                                is_resolved=False,
                            )
                        )
                        has_blocked = True

        overall_status = WarmupStatus.READY
        if has_blocked:
            overall_status = WarmupStatus.BLOCKED
        elif has_warning:
            overall_status = WarmupStatus.WARNING

        return BundleWarmupReport(
            bundle_id=bundle_id,
            overall_status=overall_status,
            checks=checks,
            checked_at=datetime.now(tz=UTC),
        )

    def activate_bundle(
        self,
        session_id: str,
        bundle_id: str,
        available_skills: set[str],
        env_vars: dict[str, str],
        force: bool = False,
    ) -> BundleActivationRecord:
        """Atomically activate all skills in the bundle for the given session."""
        if not session_id.strip():
            msg = "Session ID cannot be blank."
            raise SkillBundleError(msg)

        bundle = self._require_bundle(bundle_id)
        warmup = self.warmup_bundle(bundle_id, available_skills, env_vars)

        if warmup.overall_status == WarmupStatus.BLOCKED and not force:
            blocked_messages = [
                c.message for c in warmup.checks if c.status == WarmupStatus.BLOCKED
            ]
            msg = f"Bundle '{bundle_id}' warmup blocked: {'; '.join(blocked_messages)}"
            raise SkillBundleWarmupBlockedError(msg)

        activated_skill_ids = [s.skill_id for s in bundle.skills]
        record = BundleActivationRecord(
            session_id=session_id,
            bundle_id=bundle_id,
            activated_skills=activated_skill_ids,
            warmup_status=warmup.overall_status,
            activated_at=datetime.now(tz=UTC),
        )

        existing = self._session_activations.setdefault(session_id, [])
        # Replace if same bundle was already activated in this session
        self._session_activations[session_id] = [
            r for r in existing if r.bundle_id != bundle_id
        ] + [record]

        logger.info(
            "Activated bundle '%s' (%d skills) in session '%s' with status '%s'",
            bundle_id,
            len(activated_skill_ids),
            session_id,
            warmup.overall_status,
        )
        return record

    def deactivate_bundle(self, session_id: str, bundle_id: str) -> bool:
        """Deactivate a previously activated bundle from the specified session."""
        existing = self._session_activations.get(session_id, [])
        filtered = [r for r in existing if r.bundle_id != bundle_id]
        was_present = len(filtered) < len(existing)
        if was_present:
            self._session_activations[session_id] = filtered
            logger.info("Deactivated bundle '%s' from session '%s'", bundle_id, session_id)
        return was_present

    def get_session_activations(self, session_id: str) -> list[BundleActivationRecord]:
        """Retrieve all currently active bundle records for a session."""
        return list(self._session_activations.get(session_id, []))

    def _require_bundle(self, bundle_id: str) -> SkillBundleManifest:
        bundle = self._bundles.get(bundle_id)
        if bundle is None:
            msg = f"Skill bundle manifest '{bundle_id}' not found."
            raise SkillBundleError(msg)
        return bundle

    def _seed_default_bundles(self) -> None:
        """Seed official scenario bundles for coding, content writing, and finance."""
        coding_manifest = SkillBundleManifest(
            bundle_id="bundle_fullstack_coding",
            name="Full-Stack Code Engineering",
            description="End-to-end coding bundle with refactoring, test execution, and static linting.",
            category=BundleCategory.CODING,
            skills=[
                BundleSkillSpec("code-refactor", "Code Refactor", "Analyzes code smell and applies clean refactoring."),
                BundleSkillSpec("test-runner", "Test Execution Suite", "Runs unit tests and asserts coverage."),
                BundleSkillSpec("security-linter", "Security Linter", "Scans for secret leakage and CWE vulnerabilities.", is_optional=True),
            ],
            tags=["coding", "refactor", "pytest"],
        )

        writing_manifest = SkillBundleManifest(
            bundle_id="bundle_wechat_publisher",
            name="Official Account Content Creation",
            description="Integrated publishing suite for headline generation, copywriting, and AB testing.",
            category=BundleCategory.WRITING,
            skills=[
                BundleSkillSpec("content-topic-generator", "Topic Generator", "Brainstorms viral topics from trends."),
                BundleSkillSpec("wechat-publisher", "WeChat Article Publisher", "Formats and publishes articles.", required_env_vars=["WECHAT_APP_SECRET"]),
                BundleSkillSpec("title-ab-tester", "Headline A/B Tester", "Simulates reader clickthrough rates.", is_optional=True),
            ],
            tags=["wechat", "publishing", "copywriting"],
        )

        finance_manifest = SkillBundleManifest(
            bundle_id="bundle_finance_audit",
            name="Financial Cleaning & Reconciliation",
            description="Multi-table reconciliation, spreadsheet normalization, and invoice verification.",
            category=BundleCategory.FINANCE,
            skills=[
                BundleSkillSpec("excel-cleaner", "Excel Normalizer", "Normalizes malformed tabular data."),
                BundleSkillSpec("invoice-matcher", "Invoice Reconciliation", "Cross-checks ledger against invoice records."),
            ],
            tags=["finance", "excel", "reconciliation"],
        )

        self.register_bundle(coding_manifest)
        self.register_bundle(writing_manifest)
        self.register_bundle(finance_manifest)
