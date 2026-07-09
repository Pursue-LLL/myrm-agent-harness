"""SkillAgent explicit [use skill] preload mixin.

[POS]
Detects [use skill] prefix and pre-injects bundled SOP content before run().
"""

from __future__ import annotations

import re

from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class SkillAgentPreloadMixin:
    _USE_SKILL_PATTERN = re.compile(r"^\[use\s+([\w,\s-]+)\]\s*(.*)", re.DOTALL)

    _TOKEN_BUDGET_MAX = 12000
    """Soft cap (in estimated characters) for combined SOP injection to prevent token explosion."""

    async def _preload_explicit_skill(self, query: str) -> tuple[str, SkillMetadata | None]:
        """Detect ``[use skill_name]`` or ``[use s1,s2,s3]`` prefix and pre-inject SOP(s).

        Supports both single-skill and multi-skill (bundle) invocation. When multiple
        skill names are comma-separated, all SOPs are merged into a single injection,
        respecting ``_TOKEN_BUDGET_MAX`` to prevent token explosion.

        The ``[instruction: ...]`` suffix in the ``[use ...]`` tag is also supported
        for ephemeral bundle guidance.

        Returns:
            (modified_query, first_matched_skill_meta) — original query unchanged on failure.
        """
        match = self._USE_SKILL_PATTERN.match(query)
        if not match:
            return query, None

        raw_names = match.group(1)
        user_args = match.group(2).strip()

        skill_names = [n.strip() for n in raw_names.split(",") if n.strip()]
        if not skill_names:
            return query, None

        if not self.skill_backend:
            logger.debug("Explicit skill(s) %s requested but no skill_backend", skill_names)
            return query, None

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
            return query, None

        from myrm_agent_harness.agent.meta_tools.skills.select import (
            get_skill_document,
        )

        sop_sections: list[str] = []
        total_chars = 0
        loaded_names: list[str] = []

        for skill_meta in matched:
            try:
                sop_doc = await get_skill_document(skill_meta, self.skill_backend)
            except Exception:
                logger.warning("Failed to preload SOP for skill '%s' — skipped", skill_meta.name, exc_info=True)
                continue

            if not sop_doc or "\nError: " in sop_doc:
                logger.info("Empty or errored SOP for skill '%s' — skipped", skill_meta.name)
                continue

            if total_chars + len(sop_doc) > self._TOKEN_BUDGET_MAX and sop_sections:
                logger.warning(
                    "Token budget exceeded after %d skills (%d chars), skipping '%s'",
                    len(sop_sections),
                    total_chars,
                    skill_meta.name,
                )
                break

            section_parts = [f"--- Skill: {skill_meta.name} ---", sop_doc]

            file_listing = self._list_skill_auxiliary_files(skill_meta)
            if file_listing:
                section_parts.append(file_listing)

            if not skill_meta.available:
                reason = skill_meta.unavailable_reason or "dependency requirements not met"
                section_parts.append(f"WARNING: Skill '{skill_meta.name}' is UNAVAILABLE ({reason}).")

            sop_sections.append("\n".join(section_parts))
            total_chars += len(sop_doc)
            loaded_names.append(skill_meta.name)

        if not sop_sections:
            return query, None

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

        for skill_meta in matched:
            if skill_meta.name in loaded_names:
                record_skill_selection(skill_meta, success=True)

        return "\n".join(parts), matched[0]

    @staticmethod
    def _list_skill_auxiliary_files(skill_meta: SkillMetadata) -> str:
        """List auxiliary files under a skill's storage directory.

        Scans the allowed subdirectories (scripts/, references/, templates/, assets/)
        and returns a formatted listing for the LLM. Returns empty string if the skill
        has no storage path or no auxiliary files exist.
        """
        if not skill_meta.storage_path:
            return ""

        from pathlib import Path

        skill_dir = Path(skill_meta.storage_path)
        if not skill_dir.is_dir():
            return ""

        allowed_dirs = ("scripts", "references", "templates", "assets")
        file_entries: list[str] = []

        for subdir_name in allowed_dirs:
            subdir = skill_dir / subdir_name
            if not subdir.is_dir():
                continue
            for file_path in sorted(subdir.rglob("*")):
                if file_path.is_file():
                    rel_path = file_path.relative_to(skill_dir)
                    file_entries.append(f"- {rel_path}")

        if not file_entries:
            return ""

        return f"[This skill has supporting files in {skill_meta.name}/]:\n" + "\n".join(file_entries)

