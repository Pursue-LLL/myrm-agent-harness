"""Orchestrates experience injection across skill load, subagent spawn, and pre-write call sites.

[INPUT]
- toolkits.memory.experience_injection.models::ExperienceCallSite, ExperienceInjectionConfig,
  ExperienceInjectionResult, InjectionStatus (POS: Types and models for experience injection.)
- toolkits.memory.procedure_experience.dual_node_retriever::DualNodeFixedCountRetriever (POS: Fixed-count
  dual-node retriever for procedure-shaped experience memories.)
- toolkits.memory.procedure_experience.models::DualNodeRetrievalQuery, ProcedureMemoryEntry, RetrievalNodeKind
  (POS: Types and models for procedure experience.)

[OUTPUT]
- ExperienceInjectionEngine: Orchestrates experience injection across skill load, subagent spawn, and
  pre-write call sites.

[POS]
Orchestrates experience injection across skill load, subagent spawn, and pre-write call sites.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from myrm_agent_harness.toolkits.memory.experience_injection.models import (
    ExperienceCallSite,
    ExperienceInjectionConfig,
    ExperienceInjectionResult,
    InjectionStatus,
)
from myrm_agent_harness.toolkits.memory.procedure_experience.dual_node_retriever import (
    DualNodeFixedCountRetriever,
)
from myrm_agent_harness.toolkits.memory.procedure_experience.models import (
    DualNodeRetrievalQuery,
    ProcedureMemoryEntry,
    RetrievalNodeKind,
)

logger = logging.getLogger(__name__)


def _format_skill_experience_block(entries: tuple[ProcedureMemoryEntry, ...]) -> str:
    """Format procedure memories for Skill load injection."""
    lines: list[str] = [
        "\n<!-- [INJECTED_SKILL_EXPERIENCE] Verified operational procedures and anti-patterns -->"
    ]
    for entry in entries:
        lines.append(f"### Procedure: {entry.name}")
        lines.append(f"- **Intent**: {entry.operation_intent}")
        if entry.immutable_boundary:
            lines.append(f"- **Immutable Boundaries**: {', '.join(entry.immutable_boundary)}")
        if entry.procedure_steps:
            lines.append("- **Recommended Steps**:")
            for step in entry.procedure_steps:
                lines.append(f"  * {step}")
        if entry.anti_patterns:
            lines.append(f"- **Known Anti-Patterns**: {', '.join(entry.anti_patterns)}")
    lines.append("<!-- [/INJECTED_SKILL_EXPERIENCE] -->\n")
    return "\n".join(lines)


def _format_subagent_experience_block(entries: tuple[ProcedureMemoryEntry, ...]) -> str:
    """Format procedure memories for Subagent task prompt injection."""
    lines: list[str] = [
        "\n[EXPERIENCE CONTEXT FOR DELEGATED TASK]",
        "Adhere strictly to the following verified procedure boundaries and historical lessons:",
    ]
    for idx, entry in enumerate(entries, 1):
        lines.append(f"{idx}. [{entry.name}] {entry.operation_intent}")
        if entry.preconditions:
            lines.append(f"   - Preconditions: {'; '.join(entry.preconditions)}")
        if entry.immutable_boundary:
            lines.append(f"   - Immutable Boundaries: {'; '.join(entry.immutable_boundary)}")
        if entry.anti_patterns:
            lines.append(f"   - Anti-patterns to avoid: {'; '.join(entry.anti_patterns)}")
    lines.append("[END EXPERIENCE CONTEXT]\n")
    return "\n".join(lines)


def _format_pre_write_guard_block(entries: tuple[ProcedureMemoryEntry, ...]) -> str:
    """Format procedure memories for Pre-write guard and one-time rollback injection."""
    lines: list[str] = [
        "\n[PRE-WRITE GUARD: IMMUTABLE BOUNDARIES & PROVENANCE WARNING]",
        "Before applying disk mutations, verify the following invariants:",
    ]
    for entry in entries:
        lines.append(f"- Target Domain: {entry.name}")
        if entry.immutable_boundary:
            lines.append(f"  * Protected Boundaries (NEVER MUTATE): {'; '.join(entry.immutable_boundary)}")
        if entry.write_field_provenance:
            lines.append("  * Write Provenance Verification:")
            for field_name, source in entry.write_field_provenance.items():
                lines.append(f"    - Field '{field_name}' must derive from: {source}")
        if entry.anti_patterns:
            lines.append(f"  * Fatal Anti-Patterns: {'; '.join(entry.anti_patterns)}")
    lines.append("[END PRE-WRITE GUARD]\n")
    return "\n".join(lines)


class ExperienceInjectionEngine:
    """Orchestrates experience injection across skill load, subagent spawn, and pre-write call sites."""

    def __init__(
        self,
        retriever: DualNodeFixedCountRetriever | None = None,
        config: ExperienceInjectionConfig | None = None,
    ) -> None:
        self._retriever = retriever or DualNodeFixedCountRetriever()
        self._config = config or ExperienceInjectionConfig()
        self._injected_ids: set[str] = set()
        self._write_exp_injected_for_current_message: bool = False

    @property
    def config(self) -> ExperienceInjectionConfig:
        return self._config

    def reset_message_turn(self) -> None:
        """Reset per-message flags (e.g. before each new agent turn)."""
        self._write_exp_injected_for_current_message = False

    def reset_all_sessions(self) -> None:
        """Clear all session deduplication caches and flags."""
        self._injected_ids.clear()
        self._write_exp_injected_for_current_message = False

    def inject_skill_load(
        self,
        skill_name: str,
        raw_content: str,
        agent_id: str | None = None,
    ) -> ExperienceInjectionResult:
        """Site 1: Inject relevant procedure experiences upon loading a skill."""
        if not self._config.agent_memory_enabled:
            return ExperienceInjectionResult(
                call_site=ExperienceCallSite.SKILL_LOAD,
                status=InjectionStatus.SKIPPED_DISABLED,
                enriched_content=raw_content,
            )

        query = DualNodeRetrievalQuery(
            query_text=f"skill:{skill_name}",
            node_kind=RetrievalNodeKind.FIRST_USER,
            top_n=self._config.max_experiences_per_site,
            scope_filter=agent_id,
        )
        res = self._retriever.retrieve(query)
        candidates = [e for e in res.matched_entries if e.entry_id not in self._injected_ids]

        if not candidates:
            return ExperienceInjectionResult(
                call_site=ExperienceCallSite.SKILL_LOAD,
                status=InjectionStatus.SKIPPED_NO_MATCH,
                enriched_content=raw_content,
            )

        new_entries = tuple(candidates)
        new_ids = tuple(e.entry_id for e in new_entries)
        self._injected_ids.update(new_ids)

        block = _format_skill_experience_block(new_entries)
        enriched = f"{block}\n{raw_content}"

        return ExperienceInjectionResult(
            call_site=ExperienceCallSite.SKILL_LOAD,
            status=InjectionStatus.INJECTED,
            injected_entries=new_entries,
            enriched_content=enriched,
            rollback_required=False,
            injected_ids=new_ids,
        )

    def inject_subagent_spawn(
        self,
        subagent_role: str,
        task_prompt: str,
        agent_id: str | None = None,
    ) -> ExperienceInjectionResult:
        """Site 2: Inject procedure experiences into subagent prompt before task dispatch."""
        if not self._config.agent_memory_enabled:
            return ExperienceInjectionResult(
                call_site=ExperienceCallSite.SUBAGENT_SPAWN,
                status=InjectionStatus.SKIPPED_DISABLED,
                enriched_content=task_prompt,
            )

        query = DualNodeRetrievalQuery(
            query_text=f"{subagent_role} {task_prompt}",
            node_kind=RetrievalNodeKind.FIRST_USER,
            top_n=self._config.max_experiences_per_site,
            scope_filter=agent_id,
        )
        res = self._retriever.retrieve(query)
        candidates = [e for e in res.matched_entries if e.entry_id not in self._injected_ids]

        if not candidates:
            return ExperienceInjectionResult(
                call_site=ExperienceCallSite.SUBAGENT_SPAWN,
                status=InjectionStatus.SKIPPED_NO_MATCH,
                enriched_content=task_prompt,
            )

        new_entries = tuple(candidates)
        new_ids = tuple(e.entry_id for e in new_entries)
        self._injected_ids.update(new_ids)

        block = _format_subagent_experience_block(new_entries)
        enriched = f"{block}\n{task_prompt}"

        return ExperienceInjectionResult(
            call_site=ExperienceCallSite.SUBAGENT_SPAWN,
            status=InjectionStatus.INJECTED,
            injected_entries=new_entries,
            enriched_content=enriched,
            rollback_required=False,
            injected_ids=new_ids,
        )

    def inject_pre_write(
        self,
        tool_name: str,
        tool_args: Mapping[str, str],
        current_context: str,
        agent_id: str | None = None,
    ) -> ExperienceInjectionResult:
        """Site 3: Guard mutating tools with immutable boundaries and trigger one-time rollback."""
        if not self._config.agent_memory_enabled or not self._config.exp_write_tools_enabled:
            return ExperienceInjectionResult(
                call_site=ExperienceCallSite.PRE_WRITE,
                status=InjectionStatus.SKIPPED_DISABLED,
                enriched_content=current_context,
            )

        if tool_name not in self._config.monitored_write_tools:
            return ExperienceInjectionResult(
                call_site=ExperienceCallSite.PRE_WRITE,
                status=InjectionStatus.SKIPPED_NO_MATCH,
                enriched_content=current_context,
            )

        # Guard: Each message turn can only trigger write rollback/injection ONCE to prevent loops
        if self._write_exp_injected_for_current_message:
            return ExperienceInjectionResult(
                call_site=ExperienceCallSite.PRE_WRITE,
                status=InjectionStatus.SKIPPED_ALREADY_INJECTED,
                enriched_content=current_context,
                rollback_required=False,
            )

        args_summary = " ".join(f"{k}:{v}" for k, v in tool_args.items() if len(str(v)) < 120)
        query = DualNodeRetrievalQuery(
            query_text=f"pre_write:{tool_name} {args_summary}",
            node_kind=RetrievalNodeKind.PRE_WRITE,
            top_n=self._config.max_experiences_per_site,
            scope_filter=agent_id,
        )
        res = self._retriever.retrieve(query)
        candidates = [e for e in res.matched_entries if e.entry_id not in self._injected_ids]

        if not candidates:
            return ExperienceInjectionResult(
                call_site=ExperienceCallSite.PRE_WRITE,
                status=InjectionStatus.SKIPPED_NO_MATCH,
                enriched_content=current_context,
            )

        new_entries = tuple(candidates)
        new_ids = tuple(e.entry_id for e in new_entries)
        self._injected_ids.update(new_ids)
        self._write_exp_injected_for_current_message = True

        block = _format_pre_write_guard_block(new_entries)
        enriched = f"{current_context}\n{block}"

        return ExperienceInjectionResult(
            call_site=ExperienceCallSite.PRE_WRITE,
            status=InjectionStatus.INJECTED,
            injected_entries=new_entries,
            enriched_content=enriched,
            rollback_required=True,
            injected_ids=new_ids,
        )
