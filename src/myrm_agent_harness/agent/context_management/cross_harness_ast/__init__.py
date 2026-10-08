"""Cross-Harness Context State AST and lossless rehydration package.

[INPUT]
- None (package facade).

[OUTPUT]
- Exports canonical session AST models, engine, hydration bridge, artifact gateway, and suite.

[POS]
- Harness context management in agent/context_management/cross_harness_ast/__init__.py.
"""

from __future__ import annotations

from .artifact_continuity_gateway import ArtifactContinuityGateway
from .ast_types import (
    ArtifactContinuityReport,
    AstArtifactRef,
    AstContentBlock,
    AstMessageRole,
    AstToolInvocation,
    AstTurn,
    ContextHealthReport,
    HarnessHotSwapBadge,
    HarnessTargetFormat,
    SessionStateAST,
)
from .cross_harness_suite import (
    CrossHarnessContextStateASTAndLosslessRehydrationSuite,
    CrossHarnessSuite,
)
from .heterogeneous_hydration_bridge import HeterogeneousContextHydrationBridge
from .state_ast_engine import SessionStateASTEngine

__all__ = [
    "ArtifactContinuityGateway",
    "ArtifactContinuityReport",
    "AstArtifactRef",
    "AstContentBlock",
    "AstMessageRole",
    "AstToolInvocation",
    "AstTurn",
    "ContextHealthReport",
    "CrossHarnessContextStateASTAndLosslessRehydrationSuite",
    "CrossHarnessSuite",
    "HarnessHotSwapBadge",
    "HarnessTargetFormat",
    "HeterogeneousContextHydrationBridge",
    "SessionStateAST",
    "SessionStateASTEngine",
]
