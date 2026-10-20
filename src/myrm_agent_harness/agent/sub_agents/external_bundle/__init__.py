"""Public interface for Heterogeneous External Agent Adapter and Subagent Bundle Manager.

[INPUT]
- bundle_registry
- multiplexer
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Public interface for Heterogeneous External Agent Adapter and Subagent Bundle Manager.

"""

from .bundle_registry import (
    ExternalAgentBundleRegistry,
    ExternalBundleNotFoundError,
    ExternalBundleSecurityViolationError,
)
from .multiplexer import (
    ConcurrencyLimitExceededError,
    ExternalSubagentMultiplexer,
)
from .types import (
    BatchDispatchResult,
    BatchDispatchTask,
    BundleExecutionModeEnum,
    ExternalAgentTypeEnum,
    ExternalBundleProfileSpec,
    SubagentInstanceRecord,
    SubagentInstanceStatusEnum,
)

__all__ = [
    "ExternalAgentTypeEnum",
    "BundleExecutionModeEnum",
    "SubagentInstanceStatusEnum",
    "ExternalBundleProfileSpec",
    "SubagentInstanceRecord",
    "BatchDispatchTask",
    "BatchDispatchResult",
    "ExternalBundleSecurityViolationError",
    "ExternalBundleNotFoundError",
    "ExternalAgentBundleRegistry",
    "ConcurrencyLimitExceededError",
    "ExternalSubagentMultiplexer",
]
