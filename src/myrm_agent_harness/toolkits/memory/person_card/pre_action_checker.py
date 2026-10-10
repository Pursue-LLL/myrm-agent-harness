"""Pre-action attribute checker for proactive relationship fulfillment.

[INPUT] Action type, participant names or IDs, and optional action context.
[OUTPUT] PreActionCheckResult with missing attributes, dietary summaries, and prompt cues.
[POS] Harness framework toolkit memory layer for proactive action verification.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.person_card.models import (
    ActionType,
    ParticipantAttributeSummary,
    PersonAttributes,
    PersonCard,
    PreActionCheckResult,
)
from myrm_agent_harness.toolkits.memory.person_card.person_card_store import (
    PersonCardStore,
)


class PreActionAttributeChecker:
    """Validates participant attributes before outbound actions and constructs prompt cues."""

    def __init__(self, store: PersonCardStore) -> None:
        self._store = store

    def check_action(
        self,
        action_type: ActionType,
        participant_names_or_ids: list[str],
        action_summary: str = "",
        agent_id: str | None = None,
    ) -> PreActionCheckResult:
        """Inspect participant attributes against the intended action requirements."""
        participants_summary: list[ParticipantAttributeSummary] = []
        warnings: list[str] = []
        has_missing = False
        has_weak = False

        for query in participant_names_or_ids:
            clean_query = query.strip()
            if not clean_query:
                continue

            # Lookup card either by direct ID or alias/name search
            card = self._store.get_person(clean_query)
            if card is None:
                matches = self._store.find_by_name_or_alias(
                    clean_query, agent_id=agent_id, include_weak=True
                )
                if matches:
                    card = matches[0]

            if card is None:
                # Unknown person entity
                missing_attrs = self._get_required_attributes(action_type)
                has_missing = True
                warnings.append(
                    f"未找到相关人「{clean_query}」的实体档案卡，建议确认并在记忆中补录其关键信息。"
                )
                participants_summary.append(
                    ParticipantAttributeSummary(
                        person_id=f"unknown_{clean_query}",
                        display_name=clean_query,
                        relation_type="other",
                        missing_critical_attributes=missing_attrs,
                        is_weak_memory=False,
                        attributes=PersonAttributes(),
                    )
                )
                continue

            # Check weak memory
            is_weak = card.decay_status == "weak"
            if is_weak:
                has_weak = True
                warnings.append(
                    f"相关人「{card.display_name}」的卡片已久未互动（衰减为弱记忆），建议先向用户确认其最新偏好。"
                )

            # Evaluate missing critical attributes
            missing_attrs = self._evaluate_missing_attributes(action_type, card)
            if missing_attrs:
                has_missing = True

            participants_summary.append(
                ParticipantAttributeSummary(
                    person_id=card.person_id,
                    display_name=card.display_name,
                    relation_type=card.relation_type,
                    dietary_restrictions=list(card.attributes.dietary_restrictions),
                    timezone=card.attributes.timezone,
                    approval_preference=card.attributes.approval_preference,
                    missing_critical_attributes=missing_attrs,
                    is_weak_memory=is_weak,
                    attributes=card.attributes,
                )
            )

        prompt_cue = self._generate_prompt_cue(
            action_type=action_type,
            action_summary=action_summary,
            participants=participants_summary,
            has_missing=has_missing,
        )

        return PreActionCheckResult(
            action_type=action_type,
            action_summary=action_summary,
            has_missing_attributes=has_missing,
            has_weak_memory_warning=has_weak,
            participants=participants_summary,
            prompt_cue=prompt_cue,
            warnings=warnings,
        )

    def _get_required_attributes(self, action_type: ActionType) -> list[str]:
        if action_type == "send_invite":
            return ["dietary_restrictions"]
        if action_type in ("send_email", "assign_task"):
            return ["timezone"]
        if action_type == "submit_approval":
            return ["approval_preference"]
        return []

    def _evaluate_missing_attributes(
        self, action_type: ActionType, card: PersonCard
    ) -> list[str]:
        missing: list[str] = []
        if action_type == "send_invite":
            if not card.attributes.dietary_restrictions:
                missing.append("dietary_restrictions")
        elif action_type in ("send_email", "assign_task"):
            if not card.attributes.timezone:
                missing.append("timezone")
        elif (
            action_type == "submit_approval"
            and not card.attributes.approval_preference
        ):
            missing.append("approval_preference")
        return missing

    def _generate_prompt_cue(
        self,
        action_type: ActionType,
        action_summary: str,
        participants: list[ParticipantAttributeSummary],
        has_missing: bool,
    ) -> str:
        if not participants:
            return ""

        parts: list[str] = []
        if action_summary:
            parts.append(f"【动作指引】准备执行：{action_summary}")
        else:
            parts.append(f"【动作指引】准备执行对外动作（类型: {action_type}）")

        count = len(participants)
        participant_snippets: list[str] = []

        for p in participants:
            notes: list[str] = []
            if action_type == "send_invite":
                if p.dietary_restrictions:
                    notes.append(f"忌口: {', '.join(p.dietary_restrictions)}")
                elif "dietary_restrictions" in p.missing_critical_attributes:
                    notes.append("⚠️ 未确认忌口")
            elif action_type in ("send_email", "assign_task"):
                if p.timezone:
                    notes.append(f"时区: {p.timezone}")
                elif "timezone" in p.missing_critical_attributes:
                    notes.append("⚠️ 未知时区")
            elif action_type == "submit_approval":
                if p.approval_preference:
                    notes.append(f"偏好: {p.approval_preference}")
                elif "approval_preference" in p.missing_critical_attributes:
                    notes.append("⚠️ 未确认审批偏好")

            if p.is_weak_memory:
                notes.append("(久未互动弱记忆)")

            detail_str = f"（{'；'.join(notes)}）" if notes else ""
            participant_snippets.append(f"{p.display_name}{detail_str}")

        parts.append(f"本次涉及 {count} 位相关人：{'、'.join(participant_snippets)}。")

        if has_missing:
            parts.append("提示：部分人员缺少关键偏好/属性，在对外发出前请主动向用户核实或提示补录。")

        return "\n".join(parts)
