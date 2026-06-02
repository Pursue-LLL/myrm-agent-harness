"""Agent factory — public entry point for creating SkillAgent instances."""

from __future__ import annotations

from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.skill_agent_factory import create_skill_agent

__all__ = ["SkillAgent", "create_skill_agent"]
