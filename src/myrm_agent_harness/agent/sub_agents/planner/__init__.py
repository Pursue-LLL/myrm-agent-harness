"""Planner Sub-agent Module

Independent task planning sub-agent with its own LLM and context.

This module contains the core planner implementation as a sub-agent.
For tool integration, see `planner_agent_tools` in this package.

Design principles (based on Manus):
- Independent agent with own system prompt
- Can use different model than main agent
- Structured output with Pydantic schemas
- External reviewer perspective

Key components:
- PlannerAgent: Core agent implementation
- Plan/PlanStep/ErrorRecord: Data schemas
- PlannerStorage: Storage adapter (current plan persistence)
- PlannerConfig: Configuration options
- PlanArchiveStore/PlanRecaller: Historical plan archive and recall (Workflow RAG)

Example:
    >>> from myrm_agent_harness.agent.sub_agents.planner import (
    ...     PlannerAgent, PlannerConfig, PlannerStorage
    ... )
    >>> from myrm_agent_harness.toolkits.storage import StorageProvider
    >>>
    >>> # Create storage
    >>> storage_backend = StorageBackend.local("./workspace")
    >>> planner_storage = PlannerStorage(storage_backend)
    >>>
    >>> # Create planner agent
    >>> config = PlannerConfig(enable_3_strike=True)
    >>> planner = PlannerAgent(llm, planner_storage, config)
    >>>
    >>> # Use planner
    >>> plan = await planner.create_plan("Build a web scraper")
    >>> updated = await planner.update_plan(plan, completed_step_id="step_1")
"""

from myrm_agent_harness.agent.sub_agents.planner.agent import PlannerAgent
from myrm_agent_harness.agent.sub_agents.planner.archive import PlanArchiveStore, PlanRecaller
from myrm_agent_harness.agent.sub_agents.planner.config import PlannerConfig, SkillSummary
from myrm_agent_harness.agent.sub_agents.planner.schemas import ErrorRecord, Plan, PlannerInput, PlanStep
from myrm_agent_harness.agent.sub_agents.planner.storage import PlannerStorage

__all__ = [
    "ErrorRecord",
    "Plan",
    "PlanArchiveStore",
    "PlanRecaller",
    "PlanStep",
    "PlannerAgent",
    "PlannerConfig",
    "PlannerInput",
    "PlannerStorage",
    "SkillSummary",
]
