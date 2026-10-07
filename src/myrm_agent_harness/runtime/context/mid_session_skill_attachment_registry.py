"""Mid-session dynamic skill and tool attachment registry.

Enables non-blocking hot-attachment and detachment of skills and tools
during live agent session turns without restarting the workflow.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.memory_reinforce_emphasis_gate import (
    MemoryReinforceEmphasisGate,
)
from myrm_agent_harness.runtime.context.memory_reinforce_skill_attach_types import (
    DynamicSkillAttachment,
    PromptEmphasisInjectionPayload,
)


class MidSessionSkillAttachmentRegistry:
    """Registry maintaining dynamically attached skills and runtime tools."""

    def __init__(self) -> None:
        self._attachments: dict[str, dict[str, DynamicSkillAttachment]] = {}

    def attach_skill(
        self,
        session_id: str,
        skill_id: str,
        skill_name: str,
        description: str,
        tool_definitions: Sequence[str],
        current_turn: int = 1,
        parameters_schema: dict[str, str] | None = None,
    ) -> DynamicSkillAttachment:
        """Dynamically attach or hot-update a skill in a running session."""
        session_skills = self._attachments.setdefault(session_id, {})
        attachment = DynamicSkillAttachment(
            skill_id=skill_id,
            skill_name=skill_name.strip(),
            description=description.strip(),
            tool_definitions=tuple(tool_definitions),
            attached_at_turn=current_turn,
            active=True,
            parameters_schema=dict(parameters_schema or {}),
        )
        session_skills[skill_id] = attachment
        return attachment

    def detach_skill(self, session_id: str, skill_id: str) -> bool:
        """Deactivate a dynamically attached skill in a live session."""
        session_skills = self._attachments.get(session_id, {})
        existing = session_skills.get(skill_id)
        if existing is None or not existing.active:
            return False

        updated = DynamicSkillAttachment(
            skill_id=existing.skill_id,
            skill_name=existing.skill_name,
            description=existing.description,
            tool_definitions=existing.tool_definitions,
            attached_at_turn=existing.attached_at_turn,
            active=False,
            parameters_schema=dict(existing.parameters_schema),
        )
        session_skills[skill_id] = updated
        return True

    def list_active_skills(
        self, session_id: str
    ) -> tuple[DynamicSkillAttachment, ...]:
        """Return all currently active attached skills for the session."""
        session_skills = self._attachments.get(session_id, {})
        return tuple(s for s in session_skills.values() if s.active)

    def get_available_tools(self, session_id: str) -> tuple[str, ...]:
        """Compute the unique collection of tool definitions provided by active skills."""
        active_skills = self.list_active_skills(session_id)
        tool_set: set[str] = set()
        for skill in active_skills:
            tool_set.update(skill.tool_definitions)
        return tuple(sorted(tool_set))

    def synthesize_runtime_context_injection(
        self,
        session_id: str,
        gate: MemoryReinforceEmphasisGate | None = None,
    ) -> PromptEmphasisInjectionPayload:
        """Synthesize runtime context injection combining emphasized rules and hot skills."""
        now = time.time()
        emphasis_block = gate.render_emphasis_prompt_block(session_id) if gate else ""
        active_rules = gate.get_active_emphasis_rules(session_id) if gate else ()
        active_skills = self.list_active_skills(session_id)

        # Append hot-attached skills block if skills exist
        if active_skills:
            skill_lines = [
                "### [DYNAMICALLY ATTACHED RUNTIME SKILLS]",
                "The following skills and tools have been hot-loaded into this session and are immediately callable:",
            ]
            for s in active_skills:
                tools_str = ", ".join(s.tool_definitions) if s.tool_definitions else "None"
                skill_lines.append(
                    f"- **{s.skill_name}** (`{s.skill_id}`): {s.description} [Tools: {tools_str}]"
                )
            skill_lines.append("")
            skill_block = "\n".join(skill_lines)
            full_prompt_block = f"{emphasis_block}\n{skill_block}".strip()
        else:
            full_prompt_block = emphasis_block.strip()

        return PromptEmphasisInjectionPayload(
            session_id=session_id,
            system_emphasis_block=full_prompt_block,
            active_attached_skills=active_skills,
            effective_rules_count=len(active_rules),
            timestamp=now,
        )
