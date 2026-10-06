# [POS] toolkits/memory/auto_recall/trigger_classifier.py
# [INPUT] types.RecallTriggerType
# [OUTPUT] ExperienceRecallTriggerClassifier

"""Deterministic and lightweight classifier for 5 high-risk recall trigger scenarios."""

from __future__ import annotations

import re

from .types import RecallTriggerType


class ExperienceRecallTriggerClassifier:
    """Classifies incoming agent turns into 5 high-risk recall scenarios or suppresses recall."""

    _WRITE_PATTERNS = re.compile(
        r"\b(?:write|modify|delete|rm|drop|overwrite|replace|edit|patch|update|commit|push|deploy|chmod|chown)\b",
        re.IGNORECASE,
    )
    _TASK_START_PATTERNS = re.compile(
        r"\b(?:initialize|init|start|begin|goal|objective|plan|new task|setup)\b",
        re.IGNORECASE,
    )
    _SUBAGENT_PATTERNS = re.compile(
        r"\b(?:delegate|subagent|spawn|worker|invoke_subagent|child agent)\b",
        re.IGNORECASE,
    )
    _SKILL_PATTERNS = re.compile(
        r"\b(?:skill|load_skill|activate_tool|plugin|load_extension)\b",
        re.IGNORECASE,
    )
    _CRON_PATTERNS = re.compile(
        r"\b(?:cron|heartbeat|schedule|periodic|timer|scheduled_task)\b",
        re.IGNORECASE,
    )

    @classmethod
    def classify(
        cls,
        event_name: str | None = None,
        tool_name: str | None = None,
        query_text: str | None = None,
    ) -> tuple[RecallTriggerType, str]:
        """Classify context signals into one of the 5 sensitive trigger types, or NONE."""
        # 1. Explicit event_name checks (fastest path)
        if event_name:
            ev = event_name.lower().strip()
            if ev in ("task_start", "task_init", "goal_init", "session_start"):
                return RecallTriggerType.TASK_START, f"Explicit event: {event_name}"
            if ev in ("skill_load", "load_skill", "skill_activate"):
                return RecallTriggerType.SKILL_LOAD, f"Explicit event: {event_name}"
            if ev in ("subagent_start", "delegate_task", "spawn_agent"):
                return RecallTriggerType.SUBAGENT_START, f"Explicit event: {event_name}"
            if ev in ("write_preflight", "file_write", "destructive_op", "pre_write"):
                return RecallTriggerType.WRITE_PREFLIGHT, f"Explicit event: {event_name}"
            if ev in ("cron_start", "cron_trigger", "heartbeat_tick", "timer_expired"):
                return RecallTriggerType.CRON_START, f"Explicit event: {event_name}"

        # 2. Tool-based checks
        if tool_name:
            tn = tool_name.lower().strip()
            if tn in ("invoke_subagent", "delegate_subagent", "subagent"):
                return RecallTriggerType.SUBAGENT_START, f"Tool: {tool_name}"
            if tn in ("write_to_file", "replace_file_content", "edit_file", "delete_file"):
                return RecallTriggerType.WRITE_PREFLIGHT, f"Tool: {tool_name}"
            if tn in ("load_skill", "activate_skill"):
                return RecallTriggerType.SKILL_LOAD, f"Tool: {tool_name}"
            if tn in ("schedule", "manage_cron", "cron"):
                return RecallTriggerType.CRON_START, f"Tool: {tool_name}"

        # 3. Text pattern heuristics
        if query_text:
            text = query_text.strip()
            if cls._WRITE_PATTERNS.search(text):
                return RecallTriggerType.WRITE_PREFLIGHT, "Text pattern matched write preflight"
            if cls._CRON_PATTERNS.search(text):
                return RecallTriggerType.CRON_START, "Text pattern matched cron trigger"
            if cls._SUBAGENT_PATTERNS.search(text):
                return RecallTriggerType.SUBAGENT_START, "Text pattern matched subagent delegation"
            if cls._SKILL_PATTERNS.search(text):
                return RecallTriggerType.SKILL_LOAD, "Text pattern matched skill activation"
            if cls._TASK_START_PATTERNS.search(text):
                return RecallTriggerType.TASK_START, "Text pattern matched task start"

        return RecallTriggerType.NONE, "Non-sensitive casual/read query; auto-recall suppressed"
