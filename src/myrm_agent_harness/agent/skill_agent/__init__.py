"""SkillAgent domain package — SkillAgent implementation and assembly.

[INPUT]
- agent.base_agent::BaseAgent (POS: Lightweight Agent base class)
- agent.skills (POS: Skill metadata type)
- agent.types::AgentRuntimeConfig (POS: Agent runtime config)
- skill_agent.factory::create_skill_agent (POS: Agent factory facade re-export)

[OUTPUT]
- SkillAgent: Skill Agent — extends BaseAgent with skill system, hooks, and session lifecycle
- wait_all_background_tasks: Graceful shutdown utility for background tasks
- create_skill_agent(): Public factory entry (re-export)
- SkillAgentReviewMixin / SkillAgentToolsMixin: extension mixins for SkillAgent
- ContextVar getters/setters (get_loaded_skills, set_memory_manager, etc.)

[POS]
SkillAgent domain: the concrete agent class, its mixins, ContextVar session state,
and the factory facade. Internal implementation lives in sibling modules; the
package root is the single import surface for this domain.
"""

from __future__ import annotations

from myrm_agent_harness.agent.skill_agent.context import (
    add_loaded_skill,
    get_loaded_skills,
    get_memory_manager,
    get_task_intent,
    reset_loaded_skills,
    set_loaded_skills,
    set_memory_manager,
    set_storage_backend,
    set_task_intent,
    track_background_task,
    wait_all_background_tasks,
)
from myrm_agent_harness.agent.skill_agent.factory import create_skill_agent
from myrm_agent_harness.agent.skill_agent.review import SkillAgentReviewMixin
from myrm_agent_harness.agent.skill_agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.skill_agent.tools import SkillAgentToolsMixin

__all__ = [
    "SkillAgent",
    "SkillAgentReviewMixin",
    "SkillAgentToolsMixin",
    "add_loaded_skill",
    "create_skill_agent",
    "get_loaded_skills",
    "get_memory_manager",
    "get_task_intent",
    "reset_loaded_skills",
    "set_loaded_skills",
    "set_memory_manager",
    "set_storage_backend",
    "set_task_intent",
    "track_background_task",
    "wait_all_background_tasks",
]
