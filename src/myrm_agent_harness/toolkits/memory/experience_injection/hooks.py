# [POS]: src/myrm_agent_harness/toolkits/memory/experience_injection/hooks.py
# [INPUT]: .models, .injection_engine (ExperienceInjectionEngine)
# [OUTPUT]: SkillLoadExperienceHook, SubagentSpawnExperienceEnricher, PreWriteInterceptor

from __future__ import annotations

import logging
from collections.abc import Mapping

from myrm_agent_harness.toolkits.memory.experience_injection.injection_engine import (
    ExperienceInjectionEngine,
)
from myrm_agent_harness.toolkits.memory.experience_injection.models import (
    ExperienceInjectionResult,
    InjectionStatus,
)

logger = logging.getLogger(__name__)


class SkillLoadExperienceHook:
    """PostCallHook adapter injecting relevant procedure experiences into skill bodies."""

    def __init__(self, engine: ExperienceInjectionEngine) -> None:
        self._engine = engine

    def enrich_skill_content(
        self,
        skill_name: str,
        skill_markdown: str,
        agent_id: str | None = None,
    ) -> str:
        """Enrich loaded skill markdown content with relevant procedure experiences."""
        result = self._engine.inject_skill_load(
            skill_name=skill_name,
            raw_content=skill_markdown,
            agent_id=agent_id,
        )
        if result.status == InjectionStatus.INJECTED:
            logger.info(
                "Injected %d experience(s) on skill load for '%s'",
                len(result.injected_entries),
                skill_name,
            )
        return result.enriched_content


class SubagentSpawnExperienceEnricher:
    """Enriches delegated task prompt with verified procedure memories prior to subagent dispatch."""

    def __init__(self, engine: ExperienceInjectionEngine) -> None:
        self._engine = engine

    def enrich_subagent_task_prompt(
        self,
        subagent_role: str,
        base_prompt: str,
        agent_id: str | None = None,
    ) -> str:
        """Enrich subagent task prompt with procedure experiences matching the role/intent."""
        result = self._engine.inject_subagent_spawn(
            subagent_role=subagent_role,
            task_prompt=base_prompt,
            agent_id=agent_id,
        )
        if result.status == InjectionStatus.INJECTED:
            logger.info(
                "Injected %d experience(s) into subagent prompt for role '%s'",
                len(result.injected_entries),
                subagent_role,
            )
        return result.enriched_content


class PreWriteInterceptor:
    """Evaluates mutating tool calls before execution, enforcing immutable boundaries and one-time rollback."""

    def __init__(self, engine: ExperienceInjectionEngine) -> None:
        self._engine = engine

    def inspect_tool_call(
        self,
        tool_name: str,
        tool_args: Mapping[str, str],
        current_context: str,
        agent_id: str | None = None,
    ) -> ExperienceInjectionResult:
        """Inspect planned tool call; if mutating and unguided, triggers one-time injection & rollback."""
        return self._engine.inject_pre_write(
            tool_name=tool_name,
            tool_args=tool_args,
            current_context=current_context,
            agent_id=agent_id,
        )
