"""Dry-run discovery protocol and best source selector for CLI tools.

Implements non-executing metadata probing (--dry-run / --manifest-info)
and automatic source selection mirroring x-cmd best-source racing.

[INPUT]
- runtime.context.progressive_cli_manifest_generator::ProgressiveCliManifestGenerator (POS: Progressive CLI
  Capability Manifest Generator conforming to llms.txt standard.)
- runtime.context.progressive_cli_manifest_types::CliToolSource, CliToolSourceKind, DryRunProbeRequest,
  DryRunProbeResult (POS: Data types and schemas for progressive CLI capability manifests and dry-run
  discovery.)

[OUTPUT]
- BestSourceSelector: Selects the highest efficiency execution source for a CLI tool.
- CliDryRunDiscoveryProtocol: Handles non-executing CLI capability discovery requests.

[POS]
Dry-run discovery protocol and best source selector for CLI tools.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.progressive_cli_manifest_generator import (
    ProgressiveCliManifestGenerator,
)
from myrm_agent_harness.runtime.context.progressive_cli_manifest_types import (
    CliToolSource,
    CliToolSourceKind,
    DryRunProbeRequest,
    DryRunProbeResult,
)


class BestSourceSelector:
    """Selects the highest efficiency execution source for a CLI tool."""

    def select_best_source(self, sources: list[CliToolSource]) -> CliToolSource | None:
        """Rank and return the optimal available source."""
        available = [s for s in sources if s.is_available]
        if not available:
            return None

        # Sort by priority (descending), then latency (ascending)
        return sorted(available, key=lambda s: (-s.priority, s.estimated_latency_ms))[0]


class CliDryRunDiscoveryProtocol:
    """Handles non-executing CLI capability discovery requests."""

    def __init__(
        self,
        manifest_generator: ProgressiveCliManifestGenerator,
        source_selector: BestSourceSelector | None = None,
    ) -> None:
        self.manifest = manifest_generator
        self.source_selector = source_selector or BestSourceSelector()

    def probe_dry_run(self, request: DryRunProbeRequest) -> DryRunProbeResult:
        """Evaluate a tool dry-run request without executing any system calls or downloads."""
        entry = self.manifest.get_entry(request.tool_name)

        if not entry:
            return DryRunProbeResult(
                tool_name=request.tool_name,
                is_supported=False,
                recommended_command=[],
                best_source_kind=CliToolSourceKind.NATIVE_PATH,
                detailed_usage="",
                will_require_network=False,
                potential_side_effects=False,
                estimated_tokens_saved=0,
                probe_notes=f"Tool '{request.tool_name}' is not registered in the CLI manifest.",
            )

        best_source = self.source_selector.select_best_source(entry.sources)
        if best_source:
            recommended_cmd = list(best_source.command_prefix) + request.proposed_args
            best_kind = best_source.source_kind
        else:
            recommended_cmd = [request.tool_name, *request.proposed_args]
            best_kind = CliToolSourceKind.NATIVE_PATH

        # Token estimate: detailed manuals are ~800 to 2000 tokens. Query uses ~50 tokens.
        estimated_saved = max(100, len(entry.detailed_usage) // 4)

        return DryRunProbeResult(
            tool_name=entry.name,
            is_supported=True,
            recommended_command=recommended_cmd,
            best_source_kind=best_kind,
            detailed_usage=entry.detailed_usage,
            will_require_network=entry.requires_network,
            potential_side_effects=entry.has_side_effects,
            estimated_tokens_saved=estimated_saved,
            probe_notes=(
                f"Selected optimal source [{best_kind.value}] without executing command or downloading assets."
            ),
        )
