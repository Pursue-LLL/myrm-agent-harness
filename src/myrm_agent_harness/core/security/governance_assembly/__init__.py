"""Governance Assembly Path Assertion & Zero-Bypass Guard Package."""

from myrm_agent_harness.core.security.governance_assembly.probe import (
    GovernanceAssemblyProbe,
)
from myrm_agent_harness.core.security.governance_assembly.recording_model import (
    RecordingChatModel,
    RecordingTurn,
    SyntheticToolCall,
)
from myrm_agent_harness.core.security.governance_assembly.types import (
    GovernanceAssemblyError,
    GovernanceMatrixReport,
    GovernanceWrapperSignature,
    IngressSource,
    JsonScalar,
    ToolCallAssemblyTrace,
    UngovernedToolExecutionError,
)
from myrm_agent_harness.core.security.governance_assembly.watchdog import (
    DEFAULT_MANDATORY_MIDDLEWARES,
    GOVERNANCE_SIGNATURE_ATTR,
    RuntimeZeroBypassWatchdog,
    get_governance_signature,
    is_governance_wrapped,
    wrap_with_governance,
)

__all__ = [
    "DEFAULT_MANDATORY_MIDDLEWARES",
    "GOVERNANCE_SIGNATURE_ATTR",
    "GovernanceAssemblyError",
    "GovernanceAssemblyProbe",
    "GovernanceMatrixReport",
    "GovernanceWrapperSignature",
    "IngressSource",
    "JsonScalar",
    "RecordingChatModel",
    "RecordingTurn",
    "RuntimeZeroBypassWatchdog",
    "SyntheticToolCall",
    "ToolCallAssemblyTrace",
    "UngovernedToolExecutionError",
    "get_governance_signature",
    "is_governance_wrapped",
    "wrap_with_governance",
]
