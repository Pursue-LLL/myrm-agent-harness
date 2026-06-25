"""Automation toolkit for agent rule management.

Provides automation rule CRUD operations as LangChain tools,
following Protocol-based dependency injection.
"""

from myrm_agent_harness.toolkits.automation.automation_agent_tools import (
    create_automation_tools,
)
from myrm_agent_harness.toolkits.automation.protocols import AutomationStore
from myrm_agent_harness.toolkits.automation.stores import InMemoryAutomationStore
from myrm_agent_harness.toolkits.automation.types import (
    ActionType,
    AutomationRule,
    AutomationRuleStatus,
    TriggerType,
)

__all__ = [
    "ActionType",
    "AutomationRule",
    "AutomationRuleStatus",
    "AutomationStore",
    "InMemoryAutomationStore",
    "TriggerType",
    "create_automation_tools",
]
