"""Core implementation of Active Skill Compaction Survival Sentinel and Reattachment Governor.

Preserves active skill execution integrity across long conversations and deep context
compactions by enforcing fingerprint anchoring, 5k single skill caps, 25k total budgets,
and most-recent-first SOP reattachment.

[INPUT]
- agent.context_management.skill_sentinel.skill_sentinel_types::ActiveSkillRecord, ReattachedSkillBlock,
  ReattachmentResult, SkillBudgetPolicy (POS: Type definitions for Active Skill Compaction Survival Sentinel
  and Reattachment Governor.)

[OUTPUT]
- ActiveSkillReattachmentGovernor: Industrial governor guaranteeing active skill survival across context
  compactions.

[POS]
Core implementation of Active Skill Compaction Survival Sentinel and Reattachment Governor.
"""

from __future__ import annotations

import hashlib
import threading

from .skill_sentinel_types import (
    ActiveSkillRecord,
    ReattachedSkillBlock,
    ReattachmentResult,
    SkillBudgetPolicy,
)


class ActiveSkillReattachmentGovernor:
    """Industrial governor guaranteeing active skill survival across context compactions."""

    ACTIVE_SKILL_TAG: str = "<active_skill_sop>"

    def __init__(self, policy: SkillBudgetPolicy | None = None) -> None:
        self.policy = policy or SkillBudgetPolicy()
        self._lock = threading.Lock()
        self._active_skills: dict[str, dict[str, ActiveSkillRecord]] = {}

    def register_skill_activation(
        self,
        session_id: str,
        turn_index: int,
        skill_name: str,
        instruction_body: str,
        is_pinned: bool = False,
    ) -> ActiveSkillRecord:
        """Register or update an active skill invocation in the session lifecycle."""
        if not skill_name.strip():
            raise ValueError("Skill name cannot be empty.")
        if not instruction_body.strip():
            raise ValueError("Skill instruction body cannot be empty.")

        content_hash = hashlib.sha256(instruction_body.encode("utf-8")).hexdigest()[:16]
        estimated_tokens = max(1, len(instruction_body) // 4)

        record = ActiveSkillRecord(
            skill_name=skill_name,
            invoked_turn_index=turn_index,
            content_hash=content_hash,
            instruction_body=instruction_body,
            estimated_tokens=estimated_tokens,
            last_accessed_turn=turn_index,
            is_pinned=is_pinned,
            drift_detected=False,
        )

        with self._lock:
            if session_id not in self._active_skills:
                self._active_skills[session_id] = {}
            self._active_skills[session_id][skill_name] = record

        return record

    def get_active_skills(self, session_id: str) -> tuple[ActiveSkillRecord, ...]:
        """Retrieve all active skills sorted by recent access and pinned priority."""
        with self._lock:
            skills_dict = self._active_skills.get(session_id, {})
            records = list(skills_dict.values())

        # Pinned skills first, then most recently accessed first
        records.sort(key=lambda s: (1 if s.is_pinned else 0, s.last_accessed_turn), reverse=True)
        return tuple(records)

    def mark_skill_drift_needed(self, session_id: str, skill_name: str) -> bool:
        """Flag an active skill as needing reinforcement due to detected intention drift."""
        with self._lock:
            skills_dict = self._active_skills.get(session_id)
            if not skills_dict or skill_name not in skills_dict:
                return False

            old_record = skills_dict[skill_name]
            updated_record = ActiveSkillRecord(
                skill_name=old_record.skill_name,
                invoked_turn_index=old_record.invoked_turn_index,
                content_hash=old_record.content_hash,
                instruction_body=old_record.instruction_body,
                estimated_tokens=old_record.estimated_tokens,
                last_accessed_turn=old_record.last_accessed_turn,
                is_pinned=old_record.is_pinned,
                drift_detected=True,
            )
            skills_dict[skill_name] = updated_record
            return True

    def governed_post_compaction_reattach(
        self,
        session_id: str,
        turn_index: int,
        messages: list[dict[str, str]],
    ) -> tuple[list[dict[str, str]], ReattachmentResult]:
        """Re-attach active skills to the message stream within 5k single and 25k total budgets."""
        active_skills = self.get_active_skills(session_id)

        reattached_blocks: list[ReattachedSkillBlock] = []
        dropped_skills: list[str] = []
        current_total_tokens = 0

        max_single = self.policy.max_single_skill_tokens
        max_total = self.policy.max_total_reattached_tokens

        for record in active_skills:
            body = record.instruction_body
            is_truncated = False
            token_cost = record.estimated_tokens

            # Enforce single skill 5,000 token cap
            if token_cost > max_single:
                cutoff_chars = max_single * 4
                body = (
                    body[:cutoff_chars]
                    + "\n... [Truncated to 5,000 tokens maximum SOP budget] ..."
                )
                token_cost = max_single
                is_truncated = True

            # Enforce cumulative 25,000 token budget (most recent first; earlier drop out)
            if current_total_tokens + token_cost > max_total:
                dropped_skills.append(record.skill_name)
                continue

            # Reinforce if drift was detected
            drift_header = (
                "⚠️ [ATTENTION: Re-emphasized SOP due to detected rule drift]\n"
                if record.drift_detected
                else ""
            )

            rendered = (
                f"### Active Skill: {record.skill_name} (Hash: {record.content_hash})\n"
                f"{drift_header}{body}"
            )

            block = ReattachedSkillBlock(
                skill_name=record.skill_name,
                truncated=is_truncated,
                tokens_used=token_cost,
                rendered_content=rendered,
            )
            reattached_blocks.append(block)
            current_total_tokens += token_cost

        # Assemble unified SOP marker
        if reattached_blocks:
            inner_content = "\n\n---\n\n".join(b.rendered_content for b in reattached_blocks)
            sop_message = {
                "role": "system",
                "content": f"{self.ACTIVE_SKILL_TAG}\n{inner_content}\n</active_skill_sop>",
            }
        else:
            sop_message = None

        # Reconstruct transcript: strip old active_skill_sop markers and re-inject updated block
        reconstructed: list[dict[str, str]] = []
        injected = False

        for msg in messages:
            content = msg.get("content", "")
            if self.ACTIVE_SKILL_TAG in content:
                continue  # Clean old skill attachment

            reconstructed.append(msg)
            # Inject immediately after the base system message if not yet injected
            if not injected and msg.get("role") == "system":
                if sop_message is not None:
                    reconstructed.append(sop_message)
                injected = True

        # If there were no prior system messages, insert at head
        if not injected and sop_message is not None:
            reconstructed.insert(0, sop_message)

        result = ReattachmentResult(
            session_id=session_id,
            turn_index=turn_index,
            reattached_skills=tuple(reattached_blocks),
            dropped_skills=tuple(dropped_skills),
            total_reattached_tokens=current_total_tokens,
            injected_tag=self.ACTIVE_SKILL_TAG,
        )

        return reconstructed, result
