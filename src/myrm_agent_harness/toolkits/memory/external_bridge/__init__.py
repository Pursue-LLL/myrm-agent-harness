"""External agent memory bridge and skill writer module.

[INPUT]
- toolkits.memory.external_bridge.conflict_detector::MemoryPluginConflictDetector (POS: Detector for
  conflicting third-party memory extensions and incompatible instructions.)
- toolkits.memory.external_bridge.models::ExternalAgentType, MemoryConflictReport, SkillBridgeAction,
  SkillInstallConfig, SkillInstallResult, SkillUninstallResult (POS: Data models and type definitions for
  external agent memory bridge and skill writing.)
- toolkits.memory.external_bridge.registry::ExternalAgentTargetRegistry (POS: Registry for external agent
  bridge targets.)
- toolkits.memory.external_bridge.skill_writer::END_MARKER, ExternalAgentSkillWriter, START_MARKER (POS:
  Safe skill installer and uninstaller with marker isolation for external agents.)
- toolkits.memory.external_bridge.targets::BaseExternalAgentTarget, ClaudeCodeBridgeTarget,
  CodexBridgeTarget, CursorBridgeTarget, HermesBridgeTarget, OpenClawBridgeTarget (POS: Target definitions
  and template generators for external agent memory bridges.)

[OUTPUT]
- END_MARKER
- START_MARKER
- BaseExternalAgentTarget
- ClaudeCodeBridgeTarget
- CodexBridgeTarget
- CursorBridgeTarget
- ExternalAgentSkillWriter
- ExternalAgentTargetRegistry
- ExternalAgentType
- HermesBridgeTarget
- MemoryConflictReport
- MemoryPluginConflictDetector
- OpenClawBridgeTarget
- SkillBridgeAction
- SkillInstallConfig
- SkillInstallResult
- SkillUninstallResult

[POS]
External agent memory bridge and skill writer module.
"""

from myrm_agent_harness.toolkits.memory.external_bridge.conflict_detector import (
    MemoryPluginConflictDetector,
)
from myrm_agent_harness.toolkits.memory.external_bridge.models import (
    ExternalAgentType,
    MemoryConflictReport,
    SkillBridgeAction,
    SkillInstallConfig,
    SkillInstallResult,
    SkillUninstallResult,
)
from myrm_agent_harness.toolkits.memory.external_bridge.registry import (
    ExternalAgentTargetRegistry,
)
from myrm_agent_harness.toolkits.memory.external_bridge.skill_writer import (
    END_MARKER,
    START_MARKER,
    ExternalAgentSkillWriter,
)
from myrm_agent_harness.toolkits.memory.external_bridge.targets import (
    BaseExternalAgentTarget,
    ClaudeCodeBridgeTarget,
    CodexBridgeTarget,
    CursorBridgeTarget,
    HermesBridgeTarget,
    OpenClawBridgeTarget,
)

__all__ = [
    "END_MARKER",
    "START_MARKER",
    "BaseExternalAgentTarget",
    "ClaudeCodeBridgeTarget",
    "CodexBridgeTarget",
    "CursorBridgeTarget",
    "ExternalAgentSkillWriter",
    "ExternalAgentTargetRegistry",
    "ExternalAgentType",
    "HermesBridgeTarget",
    "MemoryConflictReport",
    "MemoryPluginConflictDetector",
    "OpenClawBridgeTarget",
    "SkillBridgeAction",
    "SkillInstallConfig",
    "SkillInstallResult",
    "SkillUninstallResult",
]
