# [POS] src/myrm_agent_harness/toolkits/memory/override_stack/detector.py
# [INPUT] re, typing, .types.EphemeralBypassRecord, myrm_agent_harness.toolkits.memory.types.ProceduralMemory
# [OUTPUT] PlaybookConflictDetector

import re

from myrm_agent_harness.toolkits.memory.override_stack.types import (
    EphemeralBypassRecord,
)
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

_RESTRICTION_ENTITY_PATTERNS = [
    re.compile(
        r"(?:禁止|严禁|避免|不要|别用|不得|disallow|forbid|prohibit|avoid|no|never)"
        r"(?:\s*(?:使用|引入|采用|开启|配置|用|use|import|install))?\s*"
        r"([a-zA-Z][a-zA-Z0-9_\-\.]{1,29}|[\u4e00-\u9fa5]{2,10})",
        re.IGNORECASE,
    ),
]

_OVERRIDE_INTENT_SIGNALS = [
    "本次",
    "这次",
    "今天",
    "单次",
    "必须",
    "强制",
    "特许",
    "破例",
    "允许",
    "请用",
    "用一次",
    "无需遵循",
    "跳过规则",
    "忽略规约",
    "必须使用",
    "bypass",
    "override",
    "must use",
    "allow",
    "force",
]

_EXPLICIT_RULE_BYPASS_SIGNALS = ["bypass", "忽略", "跳过", "破例", "无需遵守", "ignore", "skip"]


class PlaybookConflictDetector:
    """Detects acute semantic contradictions between user turn instructions and crystallized playbooks."""

    def detect_conflict(
        self,
        query: str,
        rule: ProceduralMemory,
    ) -> EphemeralBypassRecord | None:
        """Inspect if the turn prompt explicitly mandates an action contrary to the given rule."""
        cleaned_query = query.strip()
        if not cleaned_query:
            return None

        query_lower = cleaned_query.lower()
        rule_text = f"{rule.trigger} {rule.action} {rule.content}".lower()

        # Check 1: User explicitly mentions rule ID with a bypass keyword
        if rule.id.lower() in query_lower and any(
            kw in query_lower for kw in _EXPLICIT_RULE_BYPASS_SIGNALS
        ):
            return EphemeralBypassRecord(
                rule_id=rule.id,
                rule_action=rule.action,
                conflicting_clause=cleaned_query,
                bypass_reason=f"User explicitly bypassed rule id '{rule.id}' in current turn.",
            )

        # Check 2: Extract restricted targets from the rule
        restricted_targets: set[str] = set()
        for pat in _RESTRICTION_ENTITY_PATTERNS:
            for match in pat.findall(rule_text):
                target = match.strip().lower()
                if len(target) >= 2 and target not in {
                    "使用",
                    "引入",
                    "采用",
                    "配置",
                    "用",
                    "use",
                    "import",
                }:
                    restricted_targets.add(target)

        # Merge trigger keywords if explicitly registered on the rule
        for kw in getattr(rule, "trigger_keywords", []):
            if kw and len(kw.strip()) >= 2:
                restricted_targets.add(kw.strip().lower())

        if not restricted_targets:
            return None

        # Check 3: Check if the turn query carries override intent signals
        has_override_intent = any(sig in query_lower for sig in _OVERRIDE_INTENT_SIGNALS)
        if not has_override_intent:
            return None

        # Check 4: Cross-reference restricted targets against user prompt
        for target in restricted_targets:
            if target in query_lower:
                return EphemeralBypassRecord(
                    rule_id=rule.id,
                    rule_action=rule.action,
                    conflicting_clause=cleaned_query,
                    bypass_reason=(
                        f"User prompt explicitly mandated using '{target}' under override intent, "
                        f"directly contrary to rule restriction."
                    ),
                )

        return None
