"""Zero-Token Visualization Contract package.

Deterministic runtime event mirroring and Doctor anti-LLM violation guard for
Fleet Canvas, 3D office, and avatar visualization surfaces.

[INPUT]
- contract_guard
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Zero-Token Visualization Contract package.
"""

from .contract_guard import ZeroTokenContractGuard
from .types import (
    PROTECTED_VIZ_SURFACES,
    ProtectedVizSurface,
    VizCallAuditRecord,
    ZeroTokenAuditSnapshot,
    ZeroTokenContractViolationError,
    ZeroTokenEvent,
    ZeroTokenEventSource,
    ZeroTokenEventType,
)

__all__ = [
    "PROTECTED_VIZ_SURFACES",
    "ProtectedVizSurface",
    "VizCallAuditRecord",
    "ZeroTokenAuditSnapshot",
    "ZeroTokenContractGuard",
    "ZeroTokenContractViolationError",
    "ZeroTokenEvent",
    "ZeroTokenEventSource",
    "ZeroTokenEventType",
]
