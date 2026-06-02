"""Skill review and consolidation system.

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain 消息基类)
- agent.types::AgentRunStatistics (POS: Agent 运行统计信息)

[OUTPUT]
- prune_trajectory(): 轨迹剪枝函数（压缩 chat_history）
- review_trajectory_with_llm(): 技能复盘引擎（调用 LLM 总结经验）
- SkillReviewResult: 复盘结果结构

[POS]
Background silent review and skill distillation system. Asynchronously reviews conversation history after session completion to extract reusable skill patterns.

"""

from myrm_agent_harness.agent.skills.evolution.review.pruner import prune_trajectory
from myrm_agent_harness.agent.skills.evolution.review.reviewer import SkillReviewResult, review_trajectory_with_llm

__all__ = ["SkillReviewResult", "prune_trajectory", "review_trajectory_with_llm"]
