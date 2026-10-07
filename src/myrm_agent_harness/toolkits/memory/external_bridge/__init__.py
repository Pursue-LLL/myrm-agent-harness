# [POS] src/myrm_agent_harness/toolkits/memory/external_bridge/__init__.py
# [INPUT] models.py, targets.py, registry.py, conflict_detector.py, skill_writer.py
# [OUTPUT] ExternalAgentType, SkillBridgeAction, SkillInstallConfig, SkillInstallResult, SkillUninstallResult, MemoryConflictReport, BaseExternalAgentTarget, CursorBridgeTarget, ClaudeCodeBridgeTarget, CodexBridgeTarget, HermesBridgeTarget, OpenClawBridgeTarget, ExternalAgentTargetRegistry, MemoryPluginConflictDetector, ExternalAgentSkillWriter

"""External agent memory bridge and skill writer module."""

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
