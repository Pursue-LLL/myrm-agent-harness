"""Comprehensive unit tests for Progressive CLI Capability Manifest and Dry-Run Discovery Protocol."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.cli_dry_run_protocol import (
    BestSourceSelector,
    CliDryRunDiscoveryProtocol,
)
from myrm_agent_harness.runtime.context.progressive_cli_manifest_generator import (
    ProgressiveCliManifestGenerator,
)
from myrm_agent_harness.runtime.context.progressive_cli_manifest_types import (
    CliCapabilityCategory,
    CliCapabilityEntry,
    CliToolSource,
    CliToolSourceKind,
    DryRunProbeRequest,
    ManifestFormatConfig,
)


def test_llms_txt_manifest_generation() -> None:
    """Verify generation of compact llms.txt standard capability directory."""
    gen = ProgressiveCliManifestGenerator()

    jq_entry = CliCapabilityEntry(
        name="jq",
        category=CliCapabilityCategory.DATA_ANALYSIS,
        short_summary="Command-line JSON processor and filter.",
        detailed_usage="jq -r '.key' input.json | transform data",
        tags={"json", "filter", "cli"},
    )
    ffmpeg_entry = CliCapabilityEntry(
        name="ffmpeg",
        category=CliCapabilityCategory.MEDIA_PROCESSING,
        short_summary="Cross-platform multimedia stream converter.",
        detailed_usage="ffmpeg -i input.mp4 -vn output.mp3",
        tags={"video", "audio", "transcode"},
    )

    gen.register_entries([jq_entry, ffmpeg_entry])

    output = gen.generate_llms_txt()
    assert "# CLI Capability Manifest (llms.txt standard)" in output
    assert "## data_analysis" in output
    assert "- **jq**: Command-line JSON processor and filter." in output
    assert "## media_processing" in output
    assert "- **ffmpeg**: Cross-platform multimedia stream converter." in output


def test_xml_manifest_generation() -> None:
    """Verify generation of XML capability manifest for system prompt injection."""
    gen = ProgressiveCliManifestGenerator()

    curl_entry = CliCapabilityEntry(
        name="curl",
        category=CliCapabilityCategory.NETWORK_WEB,
        short_summary="Command line tool for transferring data with URLs.",
        detailed_usage="curl -sSL https://example.com",
        requires_network=True,
        has_side_effects=False,
    )

    gen.register_entry(curl_entry)
    xml_out = gen.generate_xml_manifest()

    assert "<cli_capability_manifest>" in xml_out
    assert '<category name="network_web">' in xml_out
    assert '<tool name="curl" net="true">' in xml_out
    assert "</cli_capability_manifest>" in xml_out


def test_best_source_selector_ranking() -> None:
    """Verify BestSourceSelector prefers available, higher priority, lower latency sources."""
    selector = BestSourceSelector()

    sources = [
        CliToolSource(
            source_kind=CliToolSourceKind.PACKAGE_ECOSYSTEM,
            priority=1,
            command_prefix=["npx", "pkg"],
            is_available=True,
            estimated_latency_ms=800,
        ),
        CliToolSource(
            source_kind=CliToolSourceKind.SANDBOX_PORTABLE,
            priority=3,
            command_prefix=["/opt/bin/pkg"],
            is_available=True,
            estimated_latency_ms=20,
        ),
        CliToolSource(
            source_kind=CliToolSourceKind.NATIVE_PATH,
            priority=2,
            command_prefix=["pkg"],
            is_available=False,  # not available on host
            estimated_latency_ms=10,
        ),
    ]

    best = selector.select_best_source(sources)
    assert best is not None
    assert best.source_kind == CliToolSourceKind.SANDBOX_PORTABLE
    assert best.command_prefix == ["/opt/bin/pkg"]


def test_dry_run_probe_existing_tool() -> None:
    """Verify dry-run probe returns command suggestion and usage without executing system calls."""
    gen = ProgressiveCliManifestGenerator()

    ripgrep = CliCapabilityEntry(
        name="rg",
        category=CliCapabilityCategory.DEVELOPER_TOOLS,
        short_summary="Fast line-oriented search tool.",
        detailed_usage="rg -n --hidden 'pattern' path/to/dir",
        sources=[
            CliToolSource(
                source_kind=CliToolSourceKind.NATIVE_PATH,
                priority=2,
                command_prefix=["/usr/bin/rg"],
                is_available=True,
            )
        ],
        has_side_effects=False,
        requires_network=False,
    )
    gen.register_entry(ripgrep)

    protocol = CliDryRunDiscoveryProtocol(gen)
    request = DryRunProbeRequest(
        tool_name="rg",
        proposed_args=["-i", "TODO", "."],
    )

    result = protocol.probe_dry_run(request)
    assert result.is_supported is True
    assert result.recommended_command == ["/usr/bin/rg", "-i", "TODO", "."]
    assert result.best_source_kind == CliToolSourceKind.NATIVE_PATH
    assert result.will_require_network is False
    assert result.potential_side_effects is False
    assert result.estimated_tokens_saved >= 100
    assert "rg -n --hidden" in result.detailed_usage


def test_dry_run_probe_unregistered_tool() -> None:
    """Verify non-supported tools return graceful fallback result."""
    gen = ProgressiveCliManifestGenerator()
    protocol = CliDryRunDiscoveryProtocol(gen)

    request = DryRunProbeRequest(tool_name="nonexistent_tool_xyz")
    result = protocol.probe_dry_run(request)

    assert result.is_supported is False
    assert len(result.recommended_command) == 0
    assert "not registered" in result.probe_notes


def test_large_scale_manifest_token_efficiency() -> None:
    """Verify scale test: hundreds of tools rendered in compact form avoid prompt bloat."""
    gen = ProgressiveCliManifestGenerator()

    for i in range(100):
        gen.register_entry(
            CliCapabilityEntry(
                name=f"tool_{i:03d}",
                category=CliCapabilityCategory.DEVELOPER_TOOLS,
                short_summary=f"Utility helper {i} for automation.",
                detailed_usage="Full manual text with flags and extensive options " * 20,
            )
        )

    config = ManifestFormatConfig(max_entries_per_category=50)
    llms_text = gen.generate_llms_txt(config)

    # 50 entries capped
    lines = [ln for ln in llms_text.splitlines() if ln.startswith("- **tool_")]
    assert len(lines) == 50

    # Total llms text for 50 tools is compact (< 3000 chars, ~600 tokens vs 50 * 500 = 25000 tokens)
    assert len(llms_text) < 4000
