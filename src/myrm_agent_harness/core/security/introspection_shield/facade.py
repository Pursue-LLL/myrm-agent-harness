"""
[POS] src/myrm_agent_harness/core/security/introspection_shield/facade.py
[INPUT] pathlib, typing
[OUTPUT] IntrospectionShieldSuite

Unified facade orchestrating sandbox introspection blackhole protection,
fake-root redirection, and decoupled workspace template hydration.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .blackhole_policy import IntrospectionBlackholePolicy
from .types import (
    DecoupledTemplateStandard,
    HydratedTemplateRecord,
    IntrospectionShieldMetrics,
    ProbeEvaluationResult,
    ShieldActionEnum,
)
from .workspace_hydrator import DecoupledWorkspaceHydrator

logger = logging.getLogger(__name__)


class IntrospectionShieldSuite:
    """Unified security facade providing runtime introspection shielding and workspace hydration."""

    def __init__(
        self,
        custom_blackhole_patterns: tuple[str, ...] | None = None,
        enable_fake_root: bool = True,
        max_chars_per_template: int = 16000,
    ) -> None:
        self._policy = IntrospectionBlackholePolicy(
            custom_patterns=custom_blackhole_patterns,
            enable_fake_root=enable_fake_root,
        )
        self._hydrator = DecoupledWorkspaceHydrator(
            max_chars_per_template=max_chars_per_template,
        )
        self._metrics = IntrospectionShieldMetrics()

    @property
    def metrics(self) -> IntrospectionShieldMetrics:
        """Operational metrics tracking."""
        return self._metrics

    def evaluate_path(
        self,
        target_path: str,
        workspace_root: Path | None = None,
    ) -> ProbeEvaluationResult:
        """Evaluate a path access probe against introspection blackholes."""
        self._metrics.probes_evaluated += 1
        result = self._policy.evaluate_path(target_path, workspace_root=workspace_root)

        if result.is_blocked:
            self._metrics.probes_blocked += 1
            if result.action_taken == ShieldActionEnum.FAKE_ROOT_REDIRECT:
                self._metrics.fake_root_redirects += 1

        return result

    def hydrate_workspace_templates(
        self,
        workspace_dir: Path,
    ) -> dict[DecoupledTemplateStandard, HydratedTemplateRecord]:
        """Discover and hydrate standard decoupled workspace specification files."""
        records = self._hydrator.hydrate_workspace(workspace_dir)
        self._metrics.templates_hydrated += len(records)
        return records

    def scaffold_workspace_templates(
        self,
        workspace_dir: Path,
        overwrite: bool = False,
    ) -> list[str]:
        """Generate baseline open standards template files in workspace root."""
        created = self._hydrator.scaffold_defaults(workspace_dir, overwrite=overwrite)
        self._metrics.scaffolds_generated += len(created)
        return created

    def build_prompt_context(
        self,
        hydrated: dict[DecoupledTemplateStandard, HydratedTemplateRecord],
    ) -> str:
        """Compose structured XML-tagged prompt context from active templates."""
        return self._hydrator.build_prompt_context(hydrated)

    def get_blackhole_patterns(self) -> tuple[str, ...]:
        """Return all active blackhole path patterns."""
        return self._policy.patterns

    def add_blackhole_pattern(self, pattern: str) -> None:
        """Register custom runtime blackhole path pattern."""
        self._policy.add_custom_pattern(pattern)
