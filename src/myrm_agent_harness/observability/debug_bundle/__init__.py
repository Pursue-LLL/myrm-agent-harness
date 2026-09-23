"""Session debug bundle assembler.

[INPUT]
- observability.debug_bundle.types (POS: dossier DTOs)
- observability.debug_bundle.assembler (POS: redacted assembly)
- observability.debug_bundle.rerun (POS: single-variable verdict)

[OUTPUT]
- DebugBundle, BundleSection, RerunComparison re-exports
"""

from myrm_agent_harness.observability.debug_bundle.assembler import assemble_debug_bundle
from myrm_agent_harness.observability.debug_bundle.rerun import single_variable_rerun
from myrm_agent_harness.observability.debug_bundle.types import (
    BundleCompleteness,
    BundleSection,
    DebugBundle,
    RerunComparison,
    RerunVerdict,
)

__all__ = [
    "BundleCompleteness",
    "BundleSection",
    "DebugBundle",
    "RerunComparison",
    "RerunVerdict",
    "assemble_debug_bundle",
    "single_variable_rerun",
]
