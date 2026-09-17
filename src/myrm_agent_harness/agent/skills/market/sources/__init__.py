"""Skill data sources.

[INPUT]
- agent.skills.market.sources.aliyun::AliyunSource (POS: 阿里云技能源适配层)
- agent.skills.market.sources.base::SkillSource (POS: 技能源抽象基类)
- agent.skills.market.sources.github::GitHubSkillSource (POS: GitHub 技能源适配层)
- agent.skills.market.sources.github_tap::GitHubTapSkillSource
  (POS: GitHub Tap 技能源适配层)
- agent.skills.market.sources.modelscope::ModelScopeSource
  (POS: ModelScope 技能源适配层)
- agent.skills.market.sources.prebuilt::PrebuiltSkillSource
  (POS: 内置预置技能源适配层)
- agent.skills.market.sources.skills_sh::SkillsShSource
  (POS: skills.sh 技能源适配层)
- agent.skills.market.sources.static_index::StaticIndexSkillSource
  (POS: 静态索引技能源适配层)
- agent.skills.market.sources.wellknown::WellKnownSkillSource
  (POS: well-known 发现协议技能源适配层)

[OUTPUT]
- The concrete SkillSource implementations and the SkillSource abstraction

[POS]
Source registry of the skill market. Every remote catalog is adapted to one SkillSource
contract here, so the market layer stays agnostic about which registry a skill came from.
"""

from .aliyun import AliyunSource
from .base import SkillSource
from .github import GitHubSkillSource
from .github_tap import GitHubTapSkillSource
from .modelscope import ModelScopeSource
from .prebuilt import PrebuiltSkillSource
from .skills_sh import SkillsShSource
from .static_index import StaticIndexSkillSource
from .wellknown import WellKnownSkillSource

__all__ = [
    "AliyunSource",
    "GitHubSkillSource",
    "GitHubTapSkillSource",
    "ModelScopeSource",
    "PrebuiltSkillSource",
    "SkillSource",
    "SkillsShSource",
    "StaticIndexSkillSource",
    "WellKnownSkillSource",
]
