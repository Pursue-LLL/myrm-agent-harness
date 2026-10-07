"""Unit tests for TopSectionCanonicalAlignmentEngine and cross-agent prefix cache sharing.

[INPUT]
Canonical system prompt section specs, volatile content patterns, and cross-agent assembly requests.

[OUTPUT]
Verification of static prefix byte identity, volatile token interception,
and multi-agent fleet prompt alignment.

[POS]
Quality gate for Item 120 in topic_06 roadmap.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from myrm_agent_harness.runtime.context.canonical_section_registry import (
    CanonicalSystemSectionRegistry,
)
from myrm_agent_harness.runtime.context.canonical_section_types import (
    CanonicalSectionSpec,
    SectionTier,
    VolatilePollutionError,
)


def test_default_sections_and_initialization() -> None:
    registry = CanonicalSystemSectionRegistry(include_defaults=True)
    sec_core = registry.get_canonical_section("platform_core_safety")
    assert sec_core is not None
    assert sec_core.tier == SectionTier.PLATFORM_CORE
    assert sec_core.order_index == 0

    sec_tool = registry.get_canonical_section("tooling_discipline_protocol")
    assert sec_tool is not None
    assert sec_tool.tier == SectionTier.TOOLING_DISCIPLINE
    assert sec_tool.order_index == 10

    sec_collab = registry.get_canonical_section("shared_collaboration_bus")
    assert sec_collab is not None
    assert sec_collab.tier == SectionTier.SHARED_COLLABORATION
    assert sec_collab.order_index == 20


def test_volatile_pollution_detection() -> None:
    # 1. Static content -> clean
    clean_res = CanonicalSystemSectionRegistry.detect_volatile_pollution(
        "Follow strict security guidelines and output valid JSON."
    )
    assert clean_res.has_volatile_content is False
    assert len(clean_res.detected_patterns) == 0

    # 2. Date pollution (Atlas 133 upvotes rule)
    date_res = CanonicalSystemSectionRegistry.detect_volatile_pollution(
        "System initiated on 2026-10-07 for auditing."
    )
    assert date_res.has_volatile_content is True
    assert "calendar_date" in date_res.detected_patterns

    # 3. Branch & Ref pollution
    branch_res = CanonicalSystemSectionRegistry.detect_volatile_pollution(
        "Target branch is feature/new-cache-engine in repo."
    )
    assert branch_res.has_volatile_content is True
    assert "git_branch" in branch_res.detected_patterns

    # 4. Task/Session ID & UUID
    uuid_res = CanonicalSystemSectionRegistry.detect_volatile_pollution(
        "Session bound to c8f8b3c2-1234-4567-89ab-cdef01234567 for task-98765432."
    )
    assert uuid_res.has_volatile_content is True
    assert "uuid_token" in uuid_res.detected_patterns or "task_or_session_id" in uuid_res.detected_patterns


def test_strict_immutability_rejection() -> None:
    registry = CanonicalSystemSectionRegistry(include_defaults=False)
    polluted_spec = CanonicalSectionSpec(
        section_id="bad_section",
        tier=SectionTier.PLATFORM_CORE,
        order_index=1,
        title="POLLUTED_CORE",
        content="Generated at 2026-10-07 15:30:00 on branch feature/experiment",
        is_immutable=True,
    )

    with pytest.raises(VolatilePollutionError) as exc_info:
        registry.register_canonical_section(polluted_spec, strict_immutability=True)

    assert "contains volatile tokens" in str(exc_info.value)
    assert "Relocate to Section 40-49" in str(exc_info.value)


def test_tier_index_bounds_validation() -> None:
    registry = CanonicalSystemSectionRegistry(include_defaults=False)

    # PLATFORM_CORE only accepts 0..9
    invalid_spec = CanonicalSectionSpec(
        section_id="out_of_bounds",
        tier=SectionTier.PLATFORM_CORE,
        order_index=15,  # Invalid for PLATFORM_CORE
        title="BAD_INDEX",
        content="Clean content.",
        is_immutable=True,
    )
    with pytest.raises(ValueError) as exc:
        registry.register_canonical_section(invalid_spec)
    assert "out of bounds for tier" in str(exc.value)


def test_cross_agent_prompt_assembly_and_byte_identical_prefixes() -> None:
    registry = CanonicalSystemSectionRegistry(include_defaults=True)

    # Agent 1: Coordinator
    coord_role = (
        CanonicalSectionSpec(
            section_id="coordinator_role",
            tier=SectionTier.AGENT_ROLE_SPECIALIZATION,
            order_index=30,
            title="COORDINATOR_DISPATCHER",
            content="You decompose complex objectives and assign sub-tasks to specialists.",
        ),
    )
    coord_result = registry.assemble_agent_prompt(coord_role)

    # Agent 2: Coder
    coder_role = (
        CanonicalSectionSpec(
            section_id="coder_role",
            tier=SectionTier.AGENT_ROLE_SPECIALIZATION,
            order_index=30,
            title="SYSTEM_SOFTWARE_ENGINEER",
            content="You write minimal, zero-redundancy, high-performance systems code.",
        ),
    )
    coder_result = registry.assemble_agent_prompt(coder_role)

    # Agent 3: Verifier
    verifier_role = (
        CanonicalSectionSpec(
            section_id="verifier_role",
            tier=SectionTier.AGENT_ROLE_SPECIALIZATION,
            order_index=30,
            title="QUALITY_ASSURANCE_VERIFIER",
            content="You execute adversarial boundary audits and verify test evidence.",
        ),
    )
    verifier_result = registry.assemble_agent_prompt(verifier_role)

    # Verification: Shared prefixes must be 100% byte-identical
    assert coord_result.shared_prefix_prompt == coder_result.shared_prefix_prompt
    assert coder_result.shared_prefix_prompt == verifier_result.shared_prefix_prompt

    assert coord_result.shared_prefix_fingerprint == coder_result.shared_prefix_fingerprint
    assert coder_result.shared_prefix_fingerprint == verifier_result.shared_prefix_fingerprint

    # Verification report across 3 agents
    comparison = CanonicalSystemSectionRegistry.compare_cross_agent_prefixes(
        [coord_result, coder_result, verifier_result]
    )
    assert comparison.is_identical is True
    assert comparison.common_prefix_bytes == len(coord_result.shared_prefix_prompt.encode("utf-8"))
    assert comparison.discrepancy_details is None


def test_cross_agent_prefix_discrepancy_detection() -> None:
    registry1 = CanonicalSystemSectionRegistry(include_defaults=True)
    registry2 = CanonicalSystemSectionRegistry(include_defaults=False)
    registry2.register_canonical_section(
        CanonicalSectionSpec(
            section_id="platform_core_safety",
            tier=SectionTier.PLATFORM_CORE,
            order_index=0,
            title="CORE_SAFETY_AND_SYNTAX_BASELINE",
            content="Different platform baseline content here.",
        )
    )

    role_sec = (
        CanonicalSectionSpec(
            section_id="dummy_role",
            tier=SectionTier.AGENT_ROLE_SPECIALIZATION,
            order_index=30,
            title="DUMMY",
            content="Dummy role content",
        ),
    )

    res1 = registry1.assemble_agent_prompt(role_sec)
    res2 = registry2.assemble_agent_prompt(role_sec)

    comparison = CanonicalSystemSectionRegistry.compare_cross_agent_prefixes([res1, res2])
    assert comparison.is_identical is False
    assert comparison.discrepancy_details is not None
    assert "Prefix mismatch detected at agent index 1" in comparison.discrepancy_details


def test_multithreaded_assembly_thread_safety() -> None:
    registry = CanonicalSystemSectionRegistry(include_defaults=True)

    def worker(worker_id: int) -> bool:
        role = (
            CanonicalSectionSpec(
                section_id=f"agent_role_{worker_id}",
                tier=SectionTier.AGENT_ROLE_SPECIALIZATION,
                order_index=30,
                title=f"AGENT_ROLE_{worker_id}",
                content=f"Worker {worker_id} specialized instructions.",
            ),
        )
        res = registry.assemble_agent_prompt(role)
        return len(res.shared_prefix_fingerprint) == 64

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(25)]
        results = [f.result() for f in futures]

    assert all(results)
