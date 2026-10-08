"""[POS]: src/myrm_agent_harness/toolkits/memory/progressive_sidecar/__init__.py
[INPUT]: Submodules of Progressive Context Sidecar package.
[OUTPUT]: Public symbols exported for harness and server consumption.
"""

from .adapter import ProgressiveContextVFSAdapter
from .engine import ProgressiveSidecarEngine
from .models import (
    ContextTier,
    OKFFrontmatter,
    ProgressiveContextBundle,
    ProgressiveReadRequest,
    ProgressiveReadResult,
    SidecarDescriptor,
)

__all__ = [
    "ContextTier",
    "OKFFrontmatter",
    "ProgressiveContextBundle",
    "ProgressiveContextVFSAdapter",
    "ProgressiveReadRequest",
    "ProgressiveReadResult",
    "ProgressiveSidecarEngine",
    "SidecarDescriptor",
]
