"""SkillAgent hook lifecycle mixin — framework default hooks and run-scoped skill hooks.

[INPUT]
- agent.hooks.session_access::bootstrap_hook_registry, has_callable_hook (POS: session-scoped registry access)
- agent.hooks.skill_parser::parse_hooks_from_skill_md (POS: SKILL.md hook parser)
- agent.hooks.registry::HookRegistry (POS: hook storage with scoped activation)
- backends.skills.protocols::SkillBackend (POS: skill content source)

[OUTPUT]
- SkillAgentHookLifecycleMixin: `_init_hook_lifecycle` (framework hooks, once per session registry) and `_activate_skill_hooks` (skill hooks, one run)
- SkillHookActivation: handle returned by `_activate_skill_hooks`; `release()` removes exactly the hooks that activation added

[POS]
Hook registration for SkillAgent runs. Framework hooks live as long as the session registry; hooks a skill
declares in its SKILL.md live for the run that explicitly invoked the skill.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.hooks.registry import HookRegistry
    from myrm_agent_harness.agent.hooks.types import HookDefinition, HookEvent
    from myrm_agent_harness.backends.skills.protocols import SkillBackend
    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = get_agent_logger(__name__)


@dataclass(frozen=True, slots=True)
class SkillHookActivation:
    """Skill hooks one run put on the session registry."""

    registry: HookRegistry
    scopes: tuple[str, ...] = ()

    def release(self) -> None:
        """Remove the hooks this activation added; hooks owned by an enclosing run stay."""
        for scope in self.scopes:
            self.registry.release_scope(scope)


class SkillAgentHookLifecycleMixin:
    """Hook registration for SkillAgent runs."""

    skill_backend: SkillBackend | None

    def _init_hook_lifecycle(self) -> None:
        """Register framework-level default hooks once per session registry."""
        from myrm_agent_harness.agent.hooks.session_access import (
            bootstrap_hook_registry,
            has_callable_hook,
        )
        from myrm_agent_harness.agent.hooks.types import (
            CallableHookDefinition,
            HookEvent,
        )
        from myrm_agent_harness.agent.streaming.broadcast.tool_call_broadcaster import (
            register_to_hook_registry,
        )

        registry = bootstrap_hook_registry()

        # Only register broadcaster if it's not already registered. It resolves the event logger
        # per event: the run installs its own logger after this registration.
        if not has_callable_hook(registry, HookEvent.PRE_TOOL_USE, "on_pre_tool_use"):
            register_to_hook_registry(registry)

        # Register evolution sliding window hooks if integration is active
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            get_global_evolution_integration,
        )

        evo = get_global_evolution_integration()
        if evo is not None:
            evo.register_hooks(registry)

        # Register HITL correction learning hook (converts approval edits/rejects into memory)
        from myrm_agent_harness.agent.middlewares.approval.correction_learning import (
            CorrectionLearningHook,
        )

        if not has_callable_hook(registry, HookEvent.APPROVAL_CORRECTION, "on_approval_correction"):
            correction_hook = CorrectionLearningHook()
            registry.register(
                HookEvent.APPROVAL_CORRECTION,
                CallableHookDefinition(fn=correction_hook.on_approval_correction),
            )

        logger.debug(" Framework-level hooks activated (%d hooks)", registry.total_count)

    async def _activate_skill_hooks(self, skills: Sequence[SkillMetadata]) -> SkillHookActivation:
        """Put the hooks of explicitly invoked skills on the session registry for one run.

        Hooks are read from each skill's SKILL.md at activation, so edits apply on the next run.
        Reading happens first and registration last with no await in between, which keeps a
        cancelled run from leaving a half-activated set behind.
        """
        from myrm_agent_harness.agent.hooks.session_access import bootstrap_hook_registry

        resolved = [(skill, await self._resolve_skill_hooks(skill)) for skill in skills]

        registry = bootstrap_hook_registry()
        scopes: list[str] = []
        for skill, hooks in resolved:
            scope = f"skill:{skill.name}"
            if hooks and registry.activate_scope(scope, hooks):
                scopes.append(scope)
                logger.info("Hooks activated: %s (%d hooks)", skill.name, len(hooks))
        return SkillHookActivation(registry, tuple(scopes))

    async def _resolve_skill_hooks(self, skill: SkillMetadata) -> list[tuple[HookEvent, HookDefinition]]:
        """Hooks the skill declares: those already on the metadata, else parsed from its stored SKILL.md."""
        if skill.hooks:
            return skill.hooks
        if self.skill_backend is None or skill.is_mcp_skill or not skill.storage_skill_id:
            return []

        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        try:
            content = await self.skill_backend.get_skill_content(skill.storage_skill_id)
        except Exception:
            logger.warning("Failed to read SKILL.md for hooks of skill '%s'", skill.name, exc_info=True)
            return []
        hooks, _ = parse_hooks_from_skill_md(content)
        return hooks
