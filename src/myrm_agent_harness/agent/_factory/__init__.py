"""Internal SkillAgent factory assembly package.

[INPUT]
- agent._factory.builder::create_skill_agent (POS: SkillAgent assembly pipeline)

[OUTPUT]
- create_skill_agent: internal package re-export

[POS]
Internal factory package entry. Public consumers use agent.skill_agent_factory or api/.
"""

from myrm_agent_harness.agent._factory.builder import create_skill_agent

__all__ = ["create_skill_agent"]
