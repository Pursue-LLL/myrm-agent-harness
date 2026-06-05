"""Variant Generator for Skill Evolution.

Concurrently generates multiple candidate variants of a skill using LLM,
allowing the system to explore different approaches before testing.
Supports single-error, evidence-based, and description-only generation.

Uses modular prompt assembly: composable prompt modules (editing principles,
hard constraints, conservative editing, failure attribution, structured output)
are assembled per EvolutionType for precision and maintainability.

[INPUT]
- agent.skills.evolution.core.types::SkillRecord (POS: Data types for skill evolution system.)
- agent.skills.evolution.core.types::SkillEvidenceGroup (POS: Data types for skill evolution system.)

[OUTPUT]
- VariantGenerator: Generates multiple candidate patches for a skill based on error trace or aggregated evidence.

[POS]
Variant Generator for Skill Evolution.
"""

import asyncio
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.skills.evolution.core.types import (
    SkillEvidenceGroup,
    SkillRecord,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt Modules (composable building blocks)
# ---------------------------------------------------------------------------

_EDITING_PRINCIPLES = """\
## Editing Principles
- Treat the CURRENT skill as the source of truth.
- Default to targeted edits, not rewrites.
- If multiple evidence points to the same section being wrong, edit that section.
- For corner-case failures, add missing checks without changing unrelated sections.
- When fixing missing environment dependencies, write idempotent shell commands (e.g., `if ! command -v jq &> /dev/null; then sudo apt-get update && sudo apt-get install -y jq; fi`) instead of unconditionally running installation commands.
- Preserve original structure, heading order, terminology, and effective guidance.
- If the skill contains concrete API details (endpoints, ports, schemas) that are \
factually correct, KEEP them even if the agent misused them."""

_HARD_CONSTRAINTS = """\
## Hard Constraints
- Do NOT change API contracts, ports, endpoints, output paths, or payload formats \
unless evidence clearly shows they have changed.
- Do NOT remove core capabilities or tool-usage examples unrelated to failures.
- Do NOT turn the skill into a different skill with a different purpose.
- Do NOT rewrite the whole skill from scratch.
- Do NOT impose a new template or section structure unless evidence requires it.
- Do NOT add generic best-practice guidance (retry logic, caching, rate-limits) \
that the agent should handle on its own."""

_CONSERVATIVE_EDITING = """\
## Conservative Editing
- Preserve existing section headings and ordering.
- If a successful execution supports a section, leave it untouched.
- Prefer tightening an existing section over adding a brand-new one.
- New checklist items must be short and tied to observed failures."""

_FAILURE_ATTRIBUTION = """\
## Failure Attribution
Before editing, classify the failure root cause:
- **Skill problem** (wrong/missing/misleading guidance) → edit the skill.
- **Agent problem** (misuse, context overflow, not reading skill) → do NOT \
bloat the skill with agent-runtime advice. If the skill already contains \
correct info that the agent ignored, that is an AGENT problem.
- **Environment problem** (API instability, network, docker quirks) → add a \
brief note about the instability. Do NOT turn the skill into a retry tutorial.
When in doubt, prefer skipping over a speculative edit."""

_PREFERENCE_EMBEDDING = """\
## User Preference Embedding
The user expressed a STYLE/FORMAT/WORKFLOW preference (frustration signal).
This is NOT a factual correction — it's about HOW you perform tasks.
- Embed the preference as a durable constraint in the skill body.
- Place it in the most relevant existing section, or add a brief "User Preferences" \
section if no existing section fits.
- Use imperative language: "Always X" / "Never Y" / "Prefer X over Y".
- Keep it concise (1-2 sentences max per preference).
- Do NOT remove existing correct guidance — ADD the preference alongside it.
- The preference must be phrased generically enough to apply across sessions, \
not tied to a specific one-time request."""

_STRUCTURED_OUTPUT = """\
## Output Requirements
Output the updated skill content directly (no markdown fences wrapping).
After the content, append a JSON block on a new line starting with `---EDIT_SUMMARY---`:
```
---EDIT_SUMMARY---
{"preserved_sections": ["..."], "changed_sections": ["..."], "notes": "..."}
```"""

_DESCRIPTION_SYSTEM = """\
You are a skill description optimizer. Your ONLY task is to rewrite the skill's \
description for more precise triggering. Do NOT change the skill body content.

A good description must include:
- "Use when: ..." conditions (specific triggering contexts)
- "NOT for: ..." exclusion conditions (prevent false matches)
- 2-4 sentences, concise and unambiguous.

Output ONLY the new description text. Nothing else."""


class VariantGenerator:
    """Generates multiple candidate patches for a skill based on feedback/errors."""

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        self._llm = llm

    # ------------------------------------------------------------------
    # Public API: FIX / DERIVED variants (single-error based)
    # ------------------------------------------------------------------

    async def generate_variants(
        self,
        skill: SkillRecord,
        feedback: str,
        trajectory: str,
        num_variants: int = 3,
        constraints: str = "",
    ) -> list[str]:
        """Concurrently generate multiple variant patches for a skill.

        Args:
            skill: The original skill record.
            feedback: Error message or user feedback.
            trajectory: Formatted execution trace.
            num_variants: How many distinct versions to generate.
            constraints: Historic user rejection reasons that must be obeyed.

        Returns:
            List of new complete skill contents (the evolved variants).
        """
        if not self._llm:
            logger.warning("No LLM configured for VariantGenerator")
            return [skill.content]

        prompt = self._build_variant_prompt(skill, feedback, trajectory, constraints)
        variants = await self._generate_concurrent(prompt, num_variants, "variant")
        if not variants:
            logger.warning("All variant generations failed. Returning original.")
            return [skill.content]
        return variants

    # ------------------------------------------------------------------
    # Public API: Evidence-based variants
    # ------------------------------------------------------------------

    async def generate_variants_from_evidence(
        self,
        skill: SkillRecord,
        evidence: SkillEvidenceGroup,
        num_variants: int = 3,
        constraints: str = "",
    ) -> list[str]:
        """Generate variants using aggregated evidence (success + failure cases).

        Presents the LLM with both successful and failing scenarios,
        enabling smarter fixes that avoid regressions.
        """
        if not self._llm:
            logger.warning("No LLM configured for VariantGenerator")
            return [skill.content]

        prompt = self._build_evidence_prompt(skill, evidence, constraints)
        variants = await self._generate_concurrent(prompt, num_variants, "evidence_variant")
        if not variants:
            logger.warning("All evidence variant generations failed. Returning original.")
            return [skill.content]
        return variants

    # ------------------------------------------------------------------
    # Public API: Description-only variants (OPTIMIZE_DESCRIPTION)
    # ------------------------------------------------------------------

    async def generate_description_variants(
        self,
        skill: SkillRecord,
        evidence: SkillEvidenceGroup | None = None,
        num_variants: int = 3,
    ) -> list[str]:
        """Generate description-only variants for better skill matching.

        Only rewrites the skill's description (Use-when / NOT-for conditions),
        leaving the body content untouched.
        """
        if not self._llm:
            logger.warning("No LLM configured for VariantGenerator")
            return [skill.description]

        prompt = self._build_description_prompt(skill, evidence)
        return await self._generate_concurrent(prompt, num_variants, "desc_variant")

    # ------------------------------------------------------------------
    # Shared concurrent generation
    # ------------------------------------------------------------------

    async def _generate_concurrent(self, prompt: str, num_variants: int, label: str) -> list[str]:
        """Run parallel LLM calls and filter empty results."""

        async def _generate_one(index: int) -> str:
            try:
                msg = [
                    HumanMessage(content=f"{prompt}\n\nProduce variant #{index} with a distinct approach if possible.")
                ]
                resp = await self._llm.ainvoke(msg)  # type: ignore[union-attr]
                return self._extract_content(resp.content)
            except Exception as e:
                logger.error("Failed to generate %s %d: %s", label, index, e)
                return ""

        variants = await asyncio.gather(*[_generate_one(i) for i in range(num_variants)])
        valid = [v for v in variants if v.strip()]
        if not valid:
            logger.warning("All %s generations failed. Returning empty.", label)
            return []

        return valid

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_variant_prompt(self, skill: SkillRecord, feedback: str, trajectory: str, constraints: str = "") -> str:
        """Build prompt for FIX/DERIVED evolution with modular assembly."""
        is_preference = feedback.startswith("[PREFERENCE]")
        clean_feedback = feedback.removeprefix("[PREFERENCE]").strip() if is_preference else feedback

        sections = [
            "You are an expert AI agent skill optimizer.",
            f"Skill Name: {skill.name}",
            f"\nReason for Optimization / Error:\n{clean_feedback}",
        ]

        if trajectory:
            sections.append(f"\nExecution Trajectory:\n{trajectory}")

        sections.extend(
            [
                _EDITING_PRINCIPLES,
                _HARD_CONSTRAINTS,
                _CONSERVATIVE_EDITING,
            ]
        )

        if is_preference:
            sections.append(_PREFERENCE_EMBEDDING)
        else:
            sections.append(_FAILURE_ATTRIBUTION)

        traps_section = self._build_traps_section(skill)
        if traps_section:
            sections.append(traps_section)

        if constraints:
            sections.append(f"\n## Historical Constraints (MUST obey or rejection is guaranteed)\n{constraints}")

        sections.append(f"\nCurrent Skill Content:\n{skill.content[:4000]}")
        sections.append(_STRUCTURED_OUTPUT)

        return "\n\n".join(sections)

    def _build_evidence_prompt(
        self,
        skill: SkillRecord,
        evidence: SkillEvidenceGroup,
        constraints: str = "",
    ) -> str:
        """Build prompt with both success/failure evidence and modular principles."""
        sections = [
            "You are an expert AI agent skill optimizer.",
            f"Skill Name: {skill.name}",
            f"Evidence Success Rate: {evidence.evidence_success_rate:.1%} "
            f"({len(evidence.success_cases)} success / {len(evidence.failure_cases)} failure)",
        ]

        if evidence.success_cases:
            cases = evidence.success_cases[:5]
            lines = [f"- Task: {c.task_context or 'N/A'}" for c in cases]
            sections.append(
                f"## WORKING SCENARIOS ({len(evidence.success_cases)} total)\n"
                "These work correctly. Your fix MUST NOT break them:\n" + "\n".join(lines)
            )

        if evidence.failure_cases:
            cases = evidence.failure_cases[:5]
            lines = []
            for c in cases:
                err = c.error_message[:150] if c.error_message else "N/A"
                lines.append(f"- Task: {c.task_context or 'N/A'} | Error: {err}")
            sections.append(
                f"## FAILING SCENARIOS ({len(evidence.failure_cases)} total)\nThese need fixing:\n" + "\n".join(lines)
            )

        if evidence.common_error_patterns:
            lines = [f"- {p}" for p in evidence.common_error_patterns[:5]]
            sections.append("## COMMON ERROR PATTERNS\n" + "\n".join(lines))

        sections.extend(
            [
                _EDITING_PRINCIPLES,
                _HARD_CONSTRAINTS,
                _CONSERVATIVE_EDITING,
                _FAILURE_ATTRIBUTION,
            ]
        )

        traps_section = self._build_traps_section(skill)
        if traps_section:
            sections.append(traps_section)

        if constraints:
            sections.append(f"\n## Historical Constraints (MUST obey)\n{constraints}")

        sections.append(f"\nCurrent Skill Content:\n{skill.content[:4000]}")
        sections.append(_STRUCTURED_OUTPUT)

        return "\n\n".join(sections)

    def _build_description_prompt(self, skill: SkillRecord, evidence: SkillEvidenceGroup | None = None) -> str:
        """Build prompt for description-only optimization."""
        sections = [_DESCRIPTION_SYSTEM]
        sections.append(f"Skill Name: {skill.name}")
        sections.append(f"Current Description: {skill.description}")
        sections.append(f"Skill Content (for context):\n{skill.content[:2000]}")

        if evidence:
            if evidence.success_cases:
                tasks = [c.task_context or "N/A" for c in evidence.success_cases[:3]]
                sections.append("Scenarios where this skill works: " + "; ".join(tasks))
            if evidence.failure_cases:
                tasks = [c.task_context or "N/A" for c in evidence.failure_cases[:3]]
                sections.append("Scenarios where this skill was wrongly matched: " + "; ".join(tasks))

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_traps_section(skill: SkillRecord) -> str:
        """Inject high-severity traps into the prompt as additional constraints."""
        traps = skill.get_high_severity_traps(max_count=3)
        if not traps:
            return ""
        lines = [f"- [{t.get('severity', 'medium').upper()}] {t.get('description', '')}" for t in traps]
        return "## Known Traps (avoid these pitfalls)\n" + "\n".join(lines)

    @staticmethod
    def _extract_content(llm_output: str) -> str:
        """Remove markdown fences from LLM output.

        Preserves the `---EDIT_SUMMARY---` block if present, since
        proposal_builder needs it to extract structured edit metadata.
        Evaluator strips it locally before scoring.
        """
        out = llm_output.strip()
        if out.startswith("```") and out.endswith("```"):
            lines = out.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            out = "\n".join(lines).strip()
        return out
