"""Unified facade suite for canonical workspace scaffolding and zero-friction handover.

[INPUT]
- Workspace paths, target directories, product identifiers.

[OUTPUT]
- High-level orchestration for validation, sniffing, conversion, encapsulation,
  interoperability guidance, and scaffolding template generation.

[POS]
- Harness workspace rules in agent/workspace_rules/canonical_scaffolding/canonical_scaffolding_suite.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from .heterogeneous_sniffer_and_wizard import HeterogeneousWorkspaceSnifferAndWizard
from .sandboxed_safe_encapsulator import SandboxedSafeWorkspaceEncapsulator
from .scaffolding_types import (
    CanonicalScaffoldingManifest,
    EcosystemInteroperabilityReport,
    EcosystemSniffResult,
    SandboxEncapsulationRecord,
    TopologyValidationReport,
    WorkspaceEcosystemSource,
)
from .topology_validator import TopologyValidator


class CanonicalScaffoldingSuite:
    """Unified entry point for canonical workspace scaffolding, inspection, and smooth handover."""

    PRODUCT_INTEROPERABILITY_CATALOG: Mapping[str, EcosystemInteroperabilityReport] = {
        "openclaw": EcosystemInteroperabilityReport(
            product_name="OpenClaw (Peter Steinberger)",
            comparison_summary="The pioneering open-source agent kernel that established the canonical Markdown file memory + background heartbeat paradigm.",
            shared_philosophies=(
                "Local-first Markdown specification (soul.md, memory.md).",
                "Background heartbeat proactive execution loop.",
                "Zero-menu simplicity over multi-layer hierarchical complexity.",
            ),
            divergences=(
                "Myrm provides full GUI-first WebUI & Tauri desktop integrations.",
                "Myrm enforces Agent-in-Sandbox physical isolation instead of bare host execution.",
            ),
            migration_friction="ZERO",
            recommended_migration_steps=(
                "Preserve 'soul.md' and rename/symlink to 'SOUL.md'.",
                "Import existing 'skills/' directly into Myrm skill registry.",
                "Leverage 'HEARTBEAT.md' to activate instinctive background planning.",
            ),
        ),
        "metamuse": EcosystemInteroperabilityReport(
            product_name="Meta Muse",
            comparison_summary="Meta's enterprise agent product heavily inspired by OpenClaw scaffolding conventions.",
            shared_philosophies=(
                "Modular workspace file topology.",
                "Proactive opportunity sensing across daily schedules.",
            ),
            divergences=(
                "Muse binds to proprietary cloud infrastructures, whereas Myrm guarantees 100% whitebox sovereignty.",
                "Myrm provides zero cloud lock-in with localized SQLite and vector memory.",
            ),
            migration_friction="LOW",
            recommended_migration_steps=(
                "Extract '.muse/context' and map into canonical 'context/' and 'MEMORY.md'.",
                "Migrate Muse persona configurations directly into 'SOUL.md'.",
            ),
        ),
        "hermes": EcosystemInteroperabilityReport(
            product_name="Hermes Agent",
            comparison_summary="Multi-agent CLI and backend execution framework with distinct /loop and cron lifecycles.",
            shared_philosophies=(
                "Clear separation between interactive sessions and background cron tasks.",
                "Rich skill hooks and procedural rule governance.",
            ),
            divergences=(
                "Myrm integrates session-to-cron promotion directly into GUI cards.",
                "Myrm implements silent compression fallback guards to prevent memory amnesia.",
            ),
            migration_friction="LOW",
            recommended_migration_steps=(
                "Parse 'hermes.json' tool manifests into Myrm toolkits.",
                "Consolidate '.hermes/rules' into standard 'rules/' directory.",
            ),
        ),
        "cursor": EcosystemInteroperabilityReport(
            product_name="Cursor / Windsurf",
            comparison_summary="IDE-centric AI agent environments guided by project-root rules files.",
            shared_philosophies=(
                "Context-aware codebase rules (.cursorrules, .cursor/rules/).",
            ),
            divergences=(
                "IDE rules are primarily passive code generators; Myrm agents possess active autonomy and background heartbeats.",
            ),
            migration_friction="ZERO",
            recommended_migration_steps=(
                "Ingest '.cursorrules' as an initial 'SOUL.md' base policy.",
                "Import '.cursor/rules/*.mdc' directly into 'rules/' directory.",
            ),
        ),
    }

    @classmethod
    def validate_workspace(cls, root_path: str | Path) -> TopologyValidationReport:
        """Validates directory layout against canonical scaffolding standards."""
        return TopologyValidator.validate_workspace_topology(root_path)

    @classmethod
    def sniff_ecosystem(cls, root_path: str | Path) -> EcosystemSniffResult:
        """Fingerprints workspace origin signatures and extracts key metrics."""
        return HeterogeneousWorkspaceSnifferAndWizard.sniff_ecosystem(root_path)

    @classmethod
    def handover_to_canonical_manifest(cls, root_path: str | Path) -> CanonicalScaffoldingManifest:
        """Seamlessly adapts alien or local workspaces into a canonical Myrm manifest."""
        return HeterogeneousWorkspaceSnifferAndWizard.adapt_to_canonical_manifest(root_path)

    @classmethod
    def encapsulate_untrusted_workspace(
        cls,
        source_workspace_path: str | Path,
        sandbox_base_volume_dir: str | Path | None = None,
    ) -> SandboxEncapsulationRecord:
        """Scans and encapsulates untrusted external workspaces into a dedicated sandbox."""
        return SandboxedSafeWorkspaceEncapsulator.encapsulate_workspace(
            source_workspace_path=source_workspace_path,
            sandbox_base_volume_dir=sandbox_base_volume_dir,
        )

    @classmethod
    def get_interoperability_report(cls, product_key: str) -> EcosystemInteroperabilityReport:
        """Retrieves ecosystem comparison matrix and migration guidance."""
        key = product_key.lower().replace("-", "").replace("_", "").replace(" ", "")
        if "openclaw" in key:
            return cls.PRODUCT_INTEROPERABILITY_CATALOG["openclaw"]
        if "muse" in key:
            return cls.PRODUCT_INTEROPERABILITY_CATALOG["metamuse"]
        if "hermes" in key:
            return cls.PRODUCT_INTEROPERABILITY_CATALOG["hermes"]
        if "cursor" in key or "windsurf" in key:
            return cls.PRODUCT_INTEROPERABILITY_CATALOG["cursor"]

        # Default fallback report
        return EcosystemInteroperabilityReport(
            product_name=product_key,
            comparison_summary="Generic or emergent AI agent ecosystem.",
            shared_philosophies=("Modular configuration and agent prompts.",),
            divergences=("Specialized proprietary runtime vs Myrm open extensible harness.",),
            migration_friction="MODERATE",
            recommended_migration_steps=(
                "Export text prompts into 'SOUL.md'.",
                "Place project documentation in 'rules/'.",
            ),
        )

    @classmethod
    def scaffold_new_workspace(cls, target_dir: str | Path, persona_title: str = "Assistant") -> Path:
        """Creates a fresh, 100% canonical workspace scaffolding with standard files."""
        root = Path(target_dir)
        root.mkdir(parents=True, exist_ok=True)

        # Create directories
        (root / "rules").mkdir(exist_ok=True)
        (root / "skills").mkdir(exist_ok=True)
        (root / "memory").mkdir(exist_ok=True)
        (root / "agents").mkdir(exist_ok=True)

        # Create canonical files
        soul_content = f"# {persona_title}\n\nYou are a helpful, rigorous, and highly capable agent.\n"
        user_content = "# User Profile\n\n- Preferred Language: English / Chinese\n- Tone: Concise\n"
        memory_content = "# Operational Memory\n\n- Workspace initialized.\n"
        heartbeat_content = "# Heartbeat\n\n```yaml\ninterval_minutes: 30\nenabled: true\n```\n"

        (root / "SOUL.md").write_text(soul_content, encoding="utf-8")
        (root / "USER.md").write_text(user_content, encoding="utf-8")
        (root / "MEMORY.md").write_text(memory_content, encoding="utf-8")
        (root / "HEARTBEAT.md").write_text(heartbeat_content, encoding="utf-8")

        return root


# Full canonical alias
CanonicalAgentWorkspaceScaffoldingAndZeroFrictionHandoverSuite = CanonicalScaffoldingSuite
