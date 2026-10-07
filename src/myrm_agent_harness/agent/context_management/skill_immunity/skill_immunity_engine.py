"""Active Skill Context Compaction Immunity and Re-Anchor Engine (Item 213).

[INPUT]
- ActiveSkillSpec: Strongly typed specifications of registered active skills.
- SkillImmunityConfig: Config controlling immunity shielding and prompt re-anchoring.
- Messages list: Context frame representations in dict format.

[OUTPUT]
- ActiveSkillImmunityEngine: Core engine managing skill immunity and deterministic prompt re-anchoring.
- Filtered messages isolating immune skills from lossy compaction.
- ReAnchorOutcome: Detailed outcome with deterministic XML content and cache fingerprint.

[POS]
- Shields active skill SOPs from lossy compaction summarization and re-anchors
- deterministic skill specifications into prompt frames to prevent behavioral drift.
"""

from __future__ import annotations

import hashlib
import time
from typing import Sequence

from .skill_immunity_types import (
    ActiveSkillSpec,
    ReAnchorAnchorPosition,
    ReAnchorOutcome,
    SkillImmunityConfig,
    SkillImmunityScope,
)


class ActiveSkillImmunityEngine:
    """Manages skill immunity isolation and post-compaction re-anchoring into prompt frames."""

    def __init__(self, config: SkillImmunityConfig | None = None) -> None:
        self._config = config or SkillImmunityConfig()
        # session_id -> {skill_id -> ActiveSkillSpec}
        self._active_skills: dict[str, dict[str, ActiveSkillSpec]] = {}

    @property
    def config(self) -> SkillImmunityConfig:
        """Returns the current engine configuration."""
        return self._config

    def register_skill(self, session_id: str, skill: ActiveSkillSpec) -> None:
        """Registers or updates an active skill under the specified session."""
        if session_id not in self._active_skills:
            self._active_skills[session_id] = {}
        self._active_skills[session_id][skill.skill_id] = skill

    def unregister_skill(self, session_id: str, skill_id: str) -> bool:
        """Unregisters an active skill from the session."""
        session_skills = self._active_skills.get(session_id)
        if not session_skills or skill_id not in session_skills:
            return False
        del session_skills[skill_id]
        if not session_skills:
            del self._active_skills[session_id]
        return True

    def get_active_skills(self, session_id: str) -> list[ActiveSkillSpec]:
        """Returns a list of active skills registered for the session."""
        session_skills = self._active_skills.get(session_id, {})
        skills = list(session_skills.values())
        if self._config.deterministic_sorting:
            skills.sort(key=lambda s: s.skill_id)
        return skills

    def clear_session(self, session_id: str) -> None:
        """Clears all active skills for the specified session."""
        self._active_skills.pop(session_id, None)

    def is_message_immune(self, session_id: str, message: dict[str, object]) -> bool:
        """Determines if a context message possesses compaction immunity."""
        if not self._config.enabled:
            return False

        # 1. Metadata-based explicit tag
        metadata = message.get("metadata")
        if isinstance(metadata, dict):
            if metadata.get("compaction_immune") is True:
                return True
            skill_id = metadata.get("skill_id")
            if isinstance(skill_id, str):
                session_skills = self._active_skills.get(session_id, {})
                spec = session_skills.get(skill_id)
                if spec and spec.scope in (
                    SkillImmunityScope.IMMUNE_CORE,
                    SkillImmunityScope.IMMUNE_TEMPORARY,
                ):
                    return True

        # 2. Content-based XML tag recognition
        content = message.get("content")
        if isinstance(content, str):
            tag_open = f"<{self._config.xml_tag}>"
            tag_close = f"</{self._config.xml_tag}>"
            if tag_open in content and tag_close in content:
                return True

        return False

    def partition_for_compaction(
        self,
        session_id: str,
        messages: Sequence[dict[str, object]],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Partitions messages into summarizable messages and immune messages.

        Returns:
            (summarizable_messages, immune_messages)
        """
        summarizable: list[dict[str, object]] = []
        immune: list[dict[str, object]] = []

        for msg in messages:
            if self.is_message_immune(session_id, msg):
                immune.append(dict(msg))
            else:
                summarizable.append(dict(msg))

        return summarizable, immune

    def render_active_skills_xml(self, skills: Sequence[ActiveSkillSpec]) -> str:
        """Renders active skills into a canonical XML block for prompt injection."""
        if not skills:
            return ""

        sorted_skills = list(skills)
        if self._config.deterministic_sorting:
            sorted_skills.sort(key=lambda s: s.skill_id)

        tag = self._config.xml_tag
        lines: list[str] = [f"<{tag}>"]
        for s in sorted_skills:
            lines.append(f'  <skill id="{s.skill_id}" name="{s.name}" scope="{s.scope.value}">')
            if s.sop_rules:
                lines.append("    <sop_rules>")
                for rule in s.sop_rules:
                    lines.append(f"      <rule>{rule}</rule>")
                lines.append("    </sop_rules>")
            if s.system_prompt_patch:
                lines.append("    <system_prompt_patch>")
                lines.append(f"      {s.system_prompt_patch.strip()}")
                lines.append("    </system_prompt_patch>")
            lines.append("  </skill>")
        lines.append(f"</{tag}>")
        return "\n".join(lines)

    def generate_cache_fingerprint(self, xml_content: str) -> str:
        """Generates deterministic SHA256 fingerprint for provider prompt caching."""
        if not xml_content:
            return ""
        return hashlib.sha256(xml_content.encode("utf-8")).hexdigest()

    def re_anchor_active_skills(
        self,
        session_id: str,
        messages: Sequence[dict[str, object]],
    ) -> tuple[list[dict[str, object]], ReAnchorOutcome]:
        """Re-anchors active skills into compacted message sequences.

        Ensures active skill SOP rules remain intact after lossy compactions.
        """
        start_time = time.perf_counter()
        active_skills = self.get_active_skills(session_id)

        if not self._config.enabled or not active_skills:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            outcome = ReAnchorOutcome(
                re_anchored=False,
                skill_count=0,
                re_anchored_xml="",
                cache_fingerprint="",
                re_anchor_duration_ms=duration_ms,
            )
            return [dict(m) for m in messages], outcome

        xml_content = self.render_active_skills_xml(active_skills)
        fingerprint = self.generate_cache_fingerprint(xml_content)

        # Build re-anchor synthetic system message
        re_anchor_msg: dict[str, object] = {
            "role": "system",
            "content": f"[Active Skills Instruction Frame - Zero Compaction Decay]\n{xml_content}",
            "metadata": {
                "compaction_immune": True,
                "re_anchored_skill_count": len(active_skills),
                "cache_fingerprint": fingerprint,
            },
        }

        # Filter out any existing stale active_skills XML blocks to avoid duplication
        cleaned_messages: list[dict[str, object]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str) and f"<{self._config.xml_tag}>" in content:
                continue
            cleaned_messages.append(dict(msg))

        # Position determination
        pos = self._config.anchor_position
        result_messages: list[dict[str, object]] = []

        if pos == ReAnchorAnchorPosition.AFTER_SYSTEM:
            inserted = False
            for m in cleaned_messages:
                result_messages.append(m)
                if not inserted and m.get("role") == "system":
                    result_messages.append(re_anchor_msg)
                    inserted = True
            if not inserted:
                result_messages.insert(0, re_anchor_msg)

        elif pos == ReAnchorAnchorPosition.PROMPT_TAIL:
            result_messages = list(cleaned_messages)
            result_messages.append(re_anchor_msg)

        else:  # BETWEEN_SUMMARY_AND_TAIL
            # Locate compaction summary node if available, else insert before last user/assistant message
            inserted = False
            for idx, m in enumerate(cleaned_messages):
                result_messages.append(m)
                meta = m.get("metadata")
                is_summary = (
                    isinstance(meta, dict) and meta.get("compaction_summary") is True
                ) or (
                    m.get("role") == "system"
                    and isinstance(m.get("content"), str)
                    and "summary" in str(m.get("content")).lower()
                )
                if is_summary and not inserted:
                    result_messages.append(re_anchor_msg)
                    inserted = True

            if not inserted:
                # If no summary node found, insert before the last message (if any), or append
                if len(result_messages) > 1:
                    result_messages.insert(len(result_messages) - 1, re_anchor_msg)
                else:
                    result_messages.append(re_anchor_msg)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        outcome = ReAnchorOutcome(
            re_anchored=True,
            skill_count=len(active_skills),
            re_anchored_xml=xml_content,
            cache_fingerprint=fingerprint,
            re_anchor_duration_ms=duration_ms,
        )
        return result_messages, outcome
