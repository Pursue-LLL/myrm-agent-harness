"""Agent tools for automation rule management.

Single ``automation_manage`` tool with multi-action interface.

[INPUT]
- .types::AutomationRule, TriggerType, ActionType (POS: Automation domain types.)
- .protocols::AutomationStore (POS: Protocols for the automation toolkit.)

[OUTPUT]
- create_automation_tools: Create automation management tools bound to a store.

[POS]
Agent tools for automation rule management.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.toolkits.automation.types import (
    ActionType,
    AutomationRule,
    AutomationRuleStatus,
    TriggerType,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.automation.protocols import AutomationStore

logger = get_agent_logger(__name__)


def create_automation_tools(
    store: AutomationStore,
    *,
    agent_id: str | None = None,
) -> list[BaseTool]:
    """Create automation management tools.

    Args:
        store: Automation persistence store.
        agent_id: Agent ID for rule attribution.

    Returns:
        List of automation tools.
    """

    @tool("automation_manage_tool")
    async def automation_manage(
        action: Literal[
            "create_rule",
            "list_rules",
            "get_rule",
            "update_rule",
            "delete_rule",
            "enable_rule",
            "disable_rule",
        ],
        # Rule params
        rule_id: str = "",
        name: str = "",
        description: str = "",
        trigger_type: str = "event",
        trigger_config: str = "",
        action_type: str = "agent_prompt",
        action_config: str = "",
        status: str = "active",
        # Filter params
        status_filter: str = "",
        enabled_filter: str = "",
        limit: int = 20,
    ) -> str:
        """Manage automation rules. Create, list, update, enable/disable, or delete rules.

        Args:
            action: The operation to perform.
            rule_id: Rule ID (for get/update/delete/enable/disable).
            name: Rule name (for create/update).
            description: Rule description.
            trigger_type: Trigger type: "event", "schedule", "manual".
            trigger_config: JSON string for trigger configuration (e.g. '{"event": "new_message"}').
            action_type: Action type: "agent_prompt", "webhook", "notification".
            action_config: JSON string for action configuration (e.g. '{"prompt": "Summarize this"}').
            status: Rule status: "active", "paused", "disabled".
            status_filter: Filter by status.
            enabled_filter: Filter by enabled state: "true" or "false".
            limit: Max rules to return (for list_rules).

        Returns:
            JSON string with operation result.
        """
        try:
            if action == "create_rule":
                if not name:
                    return json.dumps({"error": "name is required"})

                parsed_trigger_config: dict[str, str] = {}
                if trigger_config:
                    parsed_trigger_config = json.loads(trigger_config)

                parsed_action_config: dict[str, str] = {}
                if action_config:
                    parsed_action_config = json.loads(action_config)

                try:
                    tt = TriggerType(trigger_type)
                except ValueError:
                    tt = TriggerType.EVENT

                try:
                    at = ActionType(action_type)
                except ValueError:
                    at = ActionType.AGENT_PROMPT

                rule = AutomationRule(
                    rule_id=uuid.uuid4().hex[:32],
                    name=name,
                    description=description,
                    trigger_type=tt,
                    trigger_config=parsed_trigger_config,
                    action_type=at,
                    action_config=parsed_action_config,
                    enabled=True,
                    status=AutomationRuleStatus.ACTIVE,
                    agent_id=agent_id,
                )
                saved = await store.save_rule(rule)
                return json.dumps({
                    "status": "created",
                    "rule_id": saved.rule_id,
                    "name": saved.name,
                })

            elif action == "list_rules":
                sf = None
                if status_filter:
                    with contextlib.suppress(ValueError):
                        sf = AutomationRuleStatus(status_filter)

                ef: bool | None = None
                if enabled_filter == "true":
                    ef = True
                elif enabled_filter == "false":
                    ef = False

                rules = await store.list_rules(
                    status=sf, enabled=ef, limit=limit
                )
                total = await store.count_rules(status=sf, enabled=ef)

                return json.dumps({
                    "total": total,
                    "rules": [
                        {
                            "rule_id": r.rule_id,
                            "name": r.name,
                            "trigger_type": r.trigger_type.value,
                            "action_type": r.action_type.value,
                            "enabled": r.enabled,
                            "status": r.status.value,
                            "trigger_count": r.trigger_count,
                        }
                        for r in rules
                    ],
                })

            elif action == "get_rule":
                if not rule_id:
                    return json.dumps({"error": "rule_id is required"})
                rule = await store.get_rule(rule_id)
                if not rule:
                    return json.dumps({"error": f"Rule {rule_id} not found"})
                return json.dumps({
                    "rule_id": rule.rule_id,
                    "name": rule.name,
                    "description": rule.description,
                    "trigger_type": rule.trigger_type.value,
                    "trigger_config": rule.trigger_config,
                    "action_type": rule.action_type.value,
                    "action_config": rule.action_config,
                    "enabled": rule.enabled,
                    "status": rule.status.value,
                    "trigger_count": rule.trigger_count,
                    "last_triggered_at": (
                        rule.last_triggered_at.isoformat()
                        if rule.last_triggered_at
                        else None
                    ),
                })

            elif action == "update_rule":
                if not rule_id:
                    return json.dumps({"error": "rule_id is required"})
                existing = await store.get_rule(rule_id)
                if not existing:
                    return json.dumps({"error": f"Rule {rule_id} not found"})

                if name:
                    existing.name = name
                if description:
                    existing.description = description
                if trigger_config:
                    existing.trigger_config = json.loads(trigger_config)
                if action_config:
                    existing.action_config = json.loads(action_config)

                saved = await store.save_rule(existing)
                return json.dumps({
                    "status": "updated",
                    "rule_id": saved.rule_id,
                    "name": saved.name,
                })

            elif action == "enable_rule":
                if not rule_id:
                    return json.dumps({"error": "rule_id is required"})
                existing = await store.get_rule(rule_id)
                if not existing:
                    return json.dumps({"error": f"Rule {rule_id} not found"})
                existing.enabled = True
                existing.status = AutomationRuleStatus.ACTIVE
                saved = await store.save_rule(existing)
                return json.dumps({
                    "status": "enabled",
                    "rule_id": saved.rule_id,
                    "name": saved.name,
                })

            elif action == "disable_rule":
                if not rule_id:
                    return json.dumps({"error": "rule_id is required"})
                existing = await store.get_rule(rule_id)
                if not existing:
                    return json.dumps({"error": f"Rule {rule_id} not found"})
                existing.enabled = False
                existing.status = AutomationRuleStatus.DISABLED
                saved = await store.save_rule(existing)
                return json.dumps({
                    "status": "disabled",
                    "rule_id": saved.rule_id,
                    "name": saved.name,
                })

            elif action == "delete_rule":
                if not rule_id:
                    return json.dumps({"error": "rule_id is required"})
                deleted = await store.delete_rule(rule_id)
                if not deleted:
                    return json.dumps({"error": f"Rule {rule_id} not found"})
                return json.dumps({"status": "deleted", "rule_id": rule_id})

            else:
                return json.dumps({"error": f"Unknown action: {action}"})

        except Exception as e:
            logger.warning("Automation tool error: %s", e)
            return json.dumps({"error": str(e)})

    return [automation_manage]
