"""SkillAgent explicit [use skill] preload mixin.

[OUTPUT]
- SkillAgentPreloadMixin._preload_explicit_skill(): (query, primary_skill, preloaded_skills)

[POS]
Detects [use skill] prefix and pre-injects bundled SOP content before run().
"""

from __future__ import annotations

import re

from myrm_agent_harness.backends.skills.types import SkillInstance, SkillMetadata
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class SkillAgentPreloadMixin:
    _USE_SKILL_PATTERN = re.compile(r"^\[use\s+([\w,\s-]+)\]\s*(.*)", re.DOTALL)

    _TOKEN_BUDGET_MAX = 12000
    """Soft cap (in estimated characters) for combined SOP injection to prevent token explosion."""

    async def _preload_explicit_skill(self, query: str) -> tuple[str, SkillMetadata | None, list[SkillMetadata]]:
        """Detect ``[use skill_name]`` or ``[use s1,s2,s3]`` prefix and pre-inject SOP(s).

        Supports both single-skill and multi-skill (bundle) invocation. When multiple
        skill names are comma-separated, all SOPs are merged into a single injection,
        respecting ``_TOKEN_BUDGET_MAX`` to prevent token explosion.

        The ``[instruction: ...]`` suffix in the ``[use ...]`` tag is also supported
        for ephemeral bundle guidance.

        Returns:
            (modified_query, primary_skill_meta, preloaded_skills) — on failure the
            query is unchanged and both skill slots are empty.
        """
        match = self._USE_SKILL_PATTERN.match(query)
        if not match:
            return query, None, []

        raw_names = match.group(1)
        user_args = match.group(2).strip()

        skill_names = [n.strip() for n in raw_names.split(",") if n.strip()]
        if not skill_names:
            return query, None, []

        if not self.skill_backend:
            logger.debug("Explicit skill(s) %s requested but no skill_backend", skill_names)
            return query, None, []

        skills = await self._get_cached_skills()
        skill_map = {s.name: s for s in skills}

        matched: list[SkillMetadata] = []
        for name in skill_names:
            meta = skill_map.get(name)
            if meta:
                matched.append(meta)
            else:
                logger.info("Explicit skill '%s' not found in %d skills — skipped", name, len(skills))

        if not matched:
            return query, None, []

        from myrm_agent_harness.agent.meta_tools.skills.select import (
            get_skill_document,
        )

        sop_sections: list[str] = []
        total_chars = 0
        loaded_names: list[str] = []

        for skill_meta in matched:
            try:
                skill_instance = await self._resolve_skill_instance_for_l1(skill_meta.name)
                sop_doc = await get_skill_document(
                    skill_meta,
                    self.skill_backend,
                    skill_instance=skill_instance,
                )
            except Exception:
                logger.warning("Failed to preload SOP for skill '%s' — skipped", skill_meta.name, exc_info=True)
                continue

            if not sop_doc or "\nError: " in sop_doc:
                logger.info("Empty or errored SOP for skill '%s' — skipped", skill_meta.name)
                continue

            section_parts = [f"--- Skill: {skill_meta.name} ---", sop_doc]

            if not skill_meta.available:
                reason = skill_meta.unavailable_reason or "dependency requirements not met"
                section_parts.append(f"WARNING: Skill '{skill_meta.name}' is UNAVAILABLE ({reason}).")

            section_text = "\n".join(section_parts)
            if total_chars + len(section_text) > self._TOKEN_BUDGET_MAX and sop_sections:
                logger.warning(
                    "Token budget exceeded after %d skills (%d chars), skipping '%s'",
                    len(sop_sections),
                    total_chars,
                    skill_meta.name,
                )
                break

            sop_sections.append(section_text)
            total_chars += len(section_text)
            loaded_names.append(skill_meta.name)

        if not sop_sections:
            return query, None, []

        is_bundle = len(sop_sections) > 1
        names_str = ", ".join(loaded_names)

        if is_bundle:
            header = (
                f"[IMPORTANT: The following {len(sop_sections)} skills have been preloaded as a bundle: "
                f"{names_str}. Follow ALL their SOP instructions. Do NOT call skill_select_tool "
                f"for these skills — their content is already provided below.]"
            )
        else:
            header = (
                f'[IMPORTANT: The skill "{loaded_names[0]}" has been preloaded by the user. '
                f"Follow its SOP instructions immediately. Do NOT call skill_select_tool "
                f"for this skill — its content is already provided below.]"
            )

        parts = [header, "", *sop_sections]

        if user_args:
            parts.append("")
            parts.append(user_args)

        logger.info(
            "Preloaded %d skill(s) %s — SOP injected (%d chars), user_args='%s'",
            len(sop_sections),
            loaded_names,
            total_chars,
            user_args[:80],
        )
        from myrm_agent_harness.backends.skills.usage_recorder import record_skill_selection

        preloaded_skills = [skill_meta for skill_meta in matched if skill_meta.name in loaded_names]

        for skill_meta in preloaded_skills:
            record_skill_selection(skill_meta, success=True)

        return "\n".join(parts), preloaded_skills[0], preloaded_skills

    async def _resolve_skill_instance_for_l1(self, skill_name: str) -> SkillInstance | None:
        """Resolve bound SkillInstance for L1 config footer (matches select tool SSOT)."""
        from myrm_agent_harness.backends.skills.types import SkillInstance

        state_manager = getattr(self, "state_manager", None)
        default_instances = getattr(self, "_default_skill_instances", None) or {}
        skill_backend = getattr(self, "skill_backend", None)
        if state_manager is None or not default_instances or skill_backend is None:
            return None
        instance_name = default_instances.get(skill_name)
        if not instance_name:
            return None
        try:
            instance = await state_manager.load_instance(
                backend=skill_backend,
                skill_name=skill_name,
                instance_name=instance_name,
            )
        except Exception:
            logger.debug(
                "Failed to load skill instance %s.%s for L1 footer",
                skill_name,
                instance_name,
                exc_info=True,
            )
            return None
        return instance if isinstance(instance, SkillInstance) else None
