"""Intervention memory extractor translating human interrupts into structured procedural rules."""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    HumanInterventionEvent,
    InterventionType,
    ProceduralRule,
    RuleDistillationResult,
    RuleScope,
)

_NEGATIVE_REGEX: re.Pattern[str] = re.compile(
    r"(?:don't|do not|never|stop|别|不要|严禁|禁止|不能)\s*(?:touch|modify|edit|change|overwrite|delete|remove|动|修改|编辑|覆盖|删除)\s*([^\r\n;,]+)",
    re.IGNORECASE,
)

_PREREQUISITE_REGEX: re.Pattern[str] = re.compile(
    r"(?:must first|always make sure to|before\s+(?:modifying|updating|running)|必须先|先|在.+前必须先)\s*([^\r\n;,]+)",
    re.IGNORECASE,
)

_CORRECTIVE_REGEX: re.Pattern[str] = re.compile(
    r"(?:use|prefer|switch to|采用|换用|改成)\s*([^\s,;]+?)\s*(?:instead of|rather than|而不是|非)\s*([^\s,;]+)",
    re.IGNORECASE,
)


class InterventionMemoryExtractor:
    """Extracts and consolidates procedural environment rules from runtime human interrupts."""

    def __init__(self, default_scope: RuleScope = RuleScope.WORKSPACE) -> None:
        """Initialize extractor with default scoping."""
        self._default_scope = default_scope

    def extract_from_event(
        self,
        event: HumanInterventionEvent,
        custom_now: datetime | None = None,
    ) -> ProceduralRule:
        """Distill an individual human intervention event into a formal ProceduralRule."""
        now = custom_now or datetime.now(UTC)
        rule_id = f"prule-{uuid.uuid4().hex[:12]}"
        instruction = event.user_instruction.strip()

        rule_type = event.intervention_type
        prohibited_action: str | None = None
        required_preflight: str | None = None
        trigger_pattern = event.interrupted_tool_name or ".*"

        # Check negative constraint match
        neg_match = _NEGATIVE_REGEX.search(instruction)
        if neg_match:
            rule_type = InterventionType.NEGATIVE_CONSTRAINT
            target = neg_match.group(1).strip().rstrip("。！？.!?")
            prohibited_action = f"Forbidden to modify, overwrite, or delete target '{target}'."
            # Prefer first whitespace-delimited token (e.g. filename like .env.production) as trigger
            tokens = target.split()
            trigger_pattern = tokens[0] if tokens else target

        # Check prerequisite enforcement match
        pre_match = _PREREQUISITE_REGEX.search(instruction)
        if pre_match:
            rule_type = InterventionType.PREREQUISITE_ENFORCEMENT
            req = pre_match.group(1).strip()
            required_preflight = f"Mandatory preflight step required: '{req}'."

        # Check corrective substitution match
        cor_match = _CORRECTIVE_REGEX.search(instruction)
        if cor_match:
            rule_type = InterventionType.CORRECTIVE_ACTION
            preferred, obsolete = cor_match.group(1).strip(), cor_match.group(2).strip()
            prohibited_action = f"Do not use obsolete '{obsolete}'; enforce '{preferred}'."
            trigger_pattern = obsolete

        # Fallback to interrupted tool arguments if target still generic
        if trigger_pattern == ".*" and event.interrupted_arguments:
            for k, val in event.interrupted_arguments.items():
                if any(sub in k.lower() for sub in ("path", "file", "target", "cmd")):
                    trigger_pattern = val
                    break

        scope = self._default_scope
        scope_target = event.workspace_root or ""
        if not scope_target:
            scope = RuleScope.GLOBAL

        title = f"Intervention Guard for {trigger_pattern[:30]}"

        return ProceduralRule(
            rule_id=rule_id,
            title=title,
            rule_type=rule_type,
            scope=scope,
            scope_target=scope_target,
            trigger_pattern=trigger_pattern,
            prohibited_action=prohibited_action,
            required_preflight=required_preflight,
            raw_instruction=instruction,
            confidence=0.95,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    def distill_events(
        self,
        events: Sequence[HumanInterventionEvent],
        existing_rules: Sequence[ProceduralRule] | None = None,
    ) -> RuleDistillationResult:
        """Process multiple intervention events and deduplicate/merge against existing catalog."""
        extracted: list[ProceduralRule] = []
        rule_map: dict[str, ProceduralRule] = {}

        if existing_rules:
            for r in existing_rules:
                key = f"{r.rule_type}:{r.trigger_pattern.lower()}"
                rule_map[key] = r.model_copy(deep=True)

        merged_count = 0
        for ev in events:
            new_rule = self.extract_from_event(ev)
            key = f"{new_rule.rule_type}:{new_rule.trigger_pattern.lower()}"

            if key in rule_map:
                # Merge and reinforce
                prior = rule_map[key]
                prior.confidence = min(1.0, prior.confidence + 0.05)
                prior.updated_at = new_rule.updated_at
                prior.raw_instruction = f"{prior.raw_instruction} | {new_rule.raw_instruction}"
                if new_rule.prohibited_action:
                    prior.prohibited_action = new_rule.prohibited_action
                if new_rule.required_preflight:
                    prior.required_preflight = new_rule.required_preflight
                merged_count += 1
            else:
                rule_map[key] = new_rule
                extracted.append(new_rule)

        return RuleDistillationResult(
            extracted_rules=list(rule_map.values()),
            merged_count=merged_count,
            rationale=f"Processed {len(events)} intervention events; {merged_count} reinforced, {len(extracted)} novel rules created.",
        )
