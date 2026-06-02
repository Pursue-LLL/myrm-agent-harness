"""Automation domain types.

Pure data definitions — no I/O, safe to import anywhere.
Consumed by store, tools, and application adapters.

[INPUT]
- (none)

[OUTPUT]
- AutomationRuleStatus: Rule lifecycle states.
- TriggerType: What triggers an automation rule.
- ActionType: What action the rule performs.
- AutomationRule: Domain type for automation rules.

[POS]
Automation domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class AutomationRuleStatus(StrEnum):
    """Automation rule lifecycle states."""

    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class TriggerType(StrEnum):
    """What triggers an automation rule."""

    EVENT = "event"
    SCHEDULE = "schedule"
    MANUAL = "manual"


class ActionType(StrEnum):
    """What action the rule performs."""

    AGENT_PROMPT = "agent_prompt"
    WEBHOOK = "webhook"
    NOTIFICATION = "notification"


@dataclass
class AutomationRule:
    """Automation rule domain type."""

    rule_id: str
    name: str
    description: str = ""
    trigger_type: TriggerType = TriggerType.EVENT
    trigger_config: dict[str, str] = field(default_factory=dict)
    action_type: ActionType = ActionType.AGENT_PROMPT
    action_config: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    status: AutomationRuleStatus = AutomationRuleStatus.ACTIVE
    agent_id: str | None = None
    chat_id: str | None = None
    last_triggered_at: datetime | None = None
    trigger_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)
