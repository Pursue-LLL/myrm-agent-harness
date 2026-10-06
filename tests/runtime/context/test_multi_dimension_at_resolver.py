"""Tests for Unified Multi-Dimension At-Symbol Context Resolver and Snapshot Ingestion Hub."""

from myrm_agent_harness.runtime.context.multi_dimension_at_resolver import (
    AtReferenceKind,
    MultiDimensionAtSyntaxParser,
    SnapshotCompressor,
    SnapshotDetailLevel,
    UnifiedMultiDimensionAtResolver,
)


def test_multi_dimension_at_syntax_parser():
    prompt = (
        "Please inspect @file:src/main.py and continue from @session:sess-epoch-1. "
        "Also consult @doc:system_architecture and verify @artifact:art-spec-99. "
        "Finally check @internal/helpers/utils.py for common tools."
    )

    cleaned_prompt, references = MultiDimensionAtSyntaxParser.parse_references(prompt)

    assert "inspect @file:src/main.py" in cleaned_prompt
    assert len(references) == 5

    kinds = [r.kind for r in references]
    targets = [r.target_identifier for r in references]

    assert kinds == [
        AtReferenceKind.FILE,
        AtReferenceKind.SESSION,
        AtReferenceKind.DOC,
        AtReferenceKind.ARTIFACT,
        AtReferenceKind.FILE,
    ]
    assert targets == [
        "src/main.py",
        "sess-epoch-1",
        "system_architecture",
        "art-spec-99",
        "internal/helpers/utils.py",
    ]


def test_snapshot_compressor_granularity():
    long_content = (
        "Title Header: System Blueprint\n"
        "1. Core async event loop architecture\n"
        "2. Zero-copy IPC transmission layer\n"
        "3. Distributed state snapshotting engine\n"
        "4. Redundant failover and heartbeat telemetry\n"
        "5. Automated epoch splitting for sessions over 2000 messages\n"
    )

    # 1. Full pass
    full, full_tokens = SnapshotCompressor.compress_resource(
        title="Blueprint",
        full_content=long_content,
        detail_level=SnapshotDetailLevel.FULL_PASS,
    )
    assert full == long_content
    assert full_tokens > 0

    # 2. L0 Skeleton
    l0, l0_tokens = SnapshotCompressor.compress_resource(
        title="Blueprint",
        full_content=long_content,
        detail_level=SnapshotDetailLevel.L0_SKELETON,
    )
    assert "[Blueprint] Title Header: System Blueprint..." in l0
    assert l0_tokens <= 25

    # 3. L1 Structured
    l1, l1_tokens = SnapshotCompressor.compress_resource(
        title="Blueprint",
        full_content=long_content,
        detail_level=SnapshotDetailLevel.L1_STRUCTURED,
        max_tokens=50,
    )
    assert "- Title Header: System Blueprint" in l1
    assert "- 1. Core async event loop architecture" in l1
    assert l1_tokens <= 50


def test_unified_multi_dimension_at_resolver_ingestion():
    mock_db: dict[tuple[AtReferenceKind, str], tuple[str, str]] = {
        (AtReferenceKind.FILE, "src/entry.py"): (
            "Application Entrypoint",
            "import sys\nprint('boot')\n",
        ),
        (AtReferenceKind.SESSION, "sess-01"): (
            "Previous Migration Epoch",
            "Decision: Use bun over npm.\nCompleted scaffolding.\n",
        ),
        (AtReferenceKind.AGENT, "sec-auditor"): (
            "Security Auditor Persona",
            "Profile: Strict read-only file access and secrets scanner.\n",
        ),
    }

    def sample_loader(kind: AtReferenceKind, target: str) -> tuple[str, str]:
        if (kind, target) in mock_db:
            return mock_db[(kind, target)]
        raise FileNotFoundError(f"Missing {kind}:{target}")

    user_prompt = "Refactor @file:src/entry.py aligning with @session:sess-01 under @agent:sec-auditor guidance."

    result = UnifiedMultiDimensionAtResolver.resolve_and_ingest(
        prompt=user_prompt,
        resource_loader=sample_loader,
        default_level=SnapshotDetailLevel.L1_STRUCTURED,
    )

    assert result.cleaned_prompt == user_prompt
    assert len(result.references) == 3

    assert result.references[0].badge_label == "[File: src/entry.py]"
    assert result.references[1].badge_label == "[Session: sess-01]"
    assert result.references[2].badge_label == "[Agent: sec-auditor]"

    xml = result.injected_context_xml
    assert '<at_references_context version="1.0">' in xml
    assert '<reference kind="file" target="src/entry.py"' in xml
    assert '<reference kind="session" target="sess-01"' in xml
    assert '<reference kind="agent" target="sec-auditor"' in xml
    assert "</at_references_context>" in xml
    assert result.total_tokens_consumed > 0


def test_resilient_handling_of_unresolved_reference():
    def failing_loader(kind: AtReferenceKind, target: str) -> tuple[str, str]:
        raise KeyError("Resource not present")

    prompt = "Review missing doc @doc:non_existent_guide."
    result = UnifiedMultiDimensionAtResolver.resolve_and_ingest(
        prompt=prompt,
        resource_loader=failing_loader,
    )

    assert len(result.references) == 1
    assert "Unresolved doc:non_existent_guide" in result.references[0].title
    assert "Error: 'Resource not present'" in result.references[0].snippet
    assert "<at_references_context" in result.injected_context_xml
