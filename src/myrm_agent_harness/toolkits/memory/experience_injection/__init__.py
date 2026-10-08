"""Package facade for experience injection.

[INPUT]
- toolkits.memory.experience_injection.hooks::PreWriteInterceptor, SkillLoadExperienceHook,
  SubagentSpawnExperienceEnricher (POS: PostCallHook adapter injecting relevant procedure experiences into
  skill bodies.)
- toolkits.memory.experience_injection.injection_engine::ExperienceInjectionEngine (POS: Orchestrates
  experience injection across skill load, subagent spawn, and pre-write call sites.)
- toolkits.memory.experience_injection.models::ExperienceCallSite, ExperienceInjectionConfig,
  ExperienceInjectionResult, InjectionStatus (POS: Types and models for experience injection.)

[OUTPUT]
- Re-exports: ExperienceCallSite, InjectionStatus, ExperienceInjectionConfig, ExperienceInjectionResult,
  ExperienceInjectionEngine, SkillLoadExperienceHook, SubagentSpawnExperienceEnricher, PreWriteInterceptor

[POS]
Package facade for experience injection.
"""

# [POS]: src/myrm_agent_harness/toolkits/memory/experience_injection/__init__.py
# [INPUT]: .models, .injection_engine, .hooks
# [OUTPUT]: Public exports for experience_injection package

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.experience_injection.hooks import (
    PreWriteInterceptor,
    SkillLoadExperienceHook,
    SubagentSpawnExperienceEnricher,
)
from myrm_agent_harness.toolkits.memory.experience_injection.injection_engine import (
    ExperienceInjectionEngine,
)
from myrm_agent_harness.toolkits.memory.experience_injection.models import (
    ExperienceCallSite,
    ExperienceInjectionConfig,
    ExperienceInjectionResult,
    InjectionStatus,
)

__all__ = [
    "ExperienceCallSite",
    "InjectionStatus",
    "ExperienceInjectionConfig",
    "ExperienceInjectionResult",
    "ExperienceInjectionEngine",
    "SkillLoadExperienceHook",
    "SubagentSpawnExperienceEnricher",
    "PreWriteInterceptor",
]
