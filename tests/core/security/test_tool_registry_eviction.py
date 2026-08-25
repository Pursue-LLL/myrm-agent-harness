"""Tests for dynamic tool registry eviction & thread safety."""

import threading
from myrm_agent_harness.core.security.tool_registry.registry import (
    MCPAnnotations,
    SafetyMetadata,
    evict_skill_safety_metadata,
    get_ptc_safety_metadata,
    register_ptc_safety_metadata,
    resolve_safety_metadata,
    unregister_ptc_safety_metadata,
)


def test_register_and_unregister_ptc_safety_metadata():
    skill_name = "test_custom_skill"
    tool_a = "test_tool_alpha"
    tool_b = "test_tool_beta"

    meta_a = SafetyMetadata(is_read_only=True, is_concurrent_safe=True)
    meta_b = SafetyMetadata(is_destructive=True)
    anno = MCPAnnotations(readOnlyHint=True)

    # Register tools
    register_ptc_safety_metadata(skill_name, tool_a, meta_a, anno)
    register_ptc_safety_metadata(skill_name, tool_b, meta_b, anno)

    assert get_ptc_safety_metadata(skill_name, tool_a) is not None
    assert resolve_safety_metadata(tool_a).is_read_only is True
    assert resolve_safety_metadata(tool_b).is_destructive is True

    # Unregister tool_a only
    removed = unregister_ptc_safety_metadata(skill_name, tool_a)
    assert removed is True
    assert get_ptc_safety_metadata(skill_name, tool_a) is None
    # tool_a now resolves to fail-closed defaults
    assert resolve_safety_metadata(tool_a).is_read_only is False

    # tool_b still present
    assert get_ptc_safety_metadata(skill_name, tool_b) is not None
    assert resolve_safety_metadata(tool_b).is_destructive is True

    # Unregister non-existent
    assert unregister_ptc_safety_metadata(skill_name, "non_existent") is False
    assert unregister_ptc_safety_metadata("wrong_skill", tool_b) is False

    # Cleanup
    evict_skill_safety_metadata(skill_name)


def test_evict_skill_safety_metadata():
    skill_name = "batch_evict_skill"
    tool_1 = "batch_tool_1"
    tool_2 = "batch_tool_2"

    meta = SafetyMetadata(is_concurrent_safe=True)
    anno = MCPAnnotations()

    register_ptc_safety_metadata(skill_name, tool_1, meta, anno)
    register_ptc_safety_metadata(skill_name, tool_2, meta, anno)

    assert resolve_safety_metadata(tool_1).is_concurrent_safe is True
    assert resolve_safety_metadata(tool_2).is_concurrent_safe is True

    # Evict entire skill
    count = evict_skill_safety_metadata(skill_name)
    assert count == 2

    # Both tools evicted
    assert get_ptc_safety_metadata(skill_name, tool_1) is None
    assert get_ptc_safety_metadata(skill_name, tool_2) is None
    assert resolve_safety_metadata(tool_1).is_concurrent_safe is False
    assert resolve_safety_metadata(tool_2).is_concurrent_safe is False

    # Evicting again returns 0
    assert evict_skill_safety_metadata(skill_name) == 0


def test_ptc_registry_concurrent_thread_safety():
    skill_name = "concurrent_stress_skill"
    meta = SafetyMetadata(is_read_only=True)
    anno = MCPAnnotations()

    def worker(idx: int):
        tname = f"tool_stress_{idx}"
        for _ in range(50):
            register_ptc_safety_metadata(skill_name, tname, meta, anno)
            _ = resolve_safety_metadata(tname)
            unregister_ptc_safety_metadata(skill_name, tname)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Clean up skill
    evict_skill_safety_metadata(skill_name)
