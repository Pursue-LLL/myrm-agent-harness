"""Canonical agent workspace scaffolding, sniffer, and sandbox encapsulation package.

[INPUT]
- None (package facade).

[OUTPUT]
- Exports canonical scaffolding models, validators, sniffers, encapsulators, and suite.

[POS]
- Harness workspace rules in agent/workspace_rules/canonical_scaffolding/__init__.py.
"""

from __future__ import annotations

from .canonical_scaffolding_suite import (
    CanonicalAgentWorkspaceScaffoldingAndZeroFrictionHandoverSuite,
    CanonicalScaffoldingSuite,
)
from .heterogeneous_sniffer_and_wizard import HeterogeneousWorkspaceSnifferAndWizard
from .sandboxed_safe_encapsulator import SandboxedSafeWorkspaceEncapsulator
from .scaffolding_types import (
    CanonicalScaffoldingManifest,
    EcosystemInteroperabilityReport,
    EcosystemSniffResult,
    EncapsulationSecurityLevel,
    SandboxEncapsulationRecord,
    SandboxSecurityFinding,
    ScaffoldingFileEntry,
    TopologyValidationReport,
    WorkspaceEcosystemSource,
)
from .topology_validator import TopologyValidator

__all__ = [
    "CanonicalAgentWorkspaceScaffoldingAndZeroFrictionHandoverSuite",
    "CanonicalScaffoldingManifest",
    "CanonicalScaffoldingSuite",
    "EcosystemInteroperabilityReport",
    "EcosystemSniffResult",
    "EncapsulationSecurityLevel",
    "HeterogeneousWorkspaceSnifferAndWizard",
    "SandboxEncapsulationRecord",
    "SandboxSecurityFinding",
    "SandboxedSafeWorkspaceEncapsulator",
    "ScaffoldingFileEntry",
    "TopologyValidationReport",
    "TopologyValidator",
    "WorkspaceEcosystemSource",
]
