"""Unit tests for sandbox state-aware context cache bridge and incremental patch stitching.

Verifies:
1. Probe event recording and classification of critical configs.
2. Tail-only incremental patch stitching for ordinary code edits, keeping prefix hash intact (95%+ hit ratio).
3. Controlled full prefix invalidation when critical project manifests are modified.
4. Edge conditions: empty mutations, continuous multi-turn editing, and metric tracking.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.sandbox_cache_bridge_types import (
    FileChangeKind,
    InvalidationScope,
)
from myrm_agent_harness.runtime.context.sandbox_context_cache_bridge import (
    SandboxContextCacheBridge,
)
from myrm_agent_harness.runtime.context.sandbox_fs_event_probe import (
    SandboxFsEventProbe,
)


def test_probe_event_capture_and_classification() -> None:
    probe = SandboxFsEventProbe()
    assert not probe.has_pending_changes()

    # Normal code file change
    ev1 = probe.record_event(
        file_path="src/service/worker.py",
        kind=FileChangeKind.MODIFIED,
        diff_hunk="@@ -10,2 +10,3 @@\n+import logging",
    )
    assert not ev1.is_critical_config
    assert probe.has_pending_changes()
    assert probe.pending_count() == 1

    # Critical manifest change
    ev2 = probe.record_event(
        file_path="pyproject.toml",
        kind=FileChangeKind.MODIFIED,
        diff_hunk="@@ -5,1 +5,1 @@\n-version = '1.0.0'\n+version = '1.0.1'",
    )
    assert ev2.is_critical_config
    assert probe.pending_count() == 2

    # Drain and compile patch
    patch = probe.drain_and_compile_patch(base_prefix_hash="mock_hash_123")
    assert not probe.has_pending_changes()
    assert patch.events_count == 2
    assert patch.invalidation_scope == InvalidationScope.FULL_PREFIX_INVALIDATION
    assert "src/service/worker.py" in patch.formatted_tail_diff
    assert "pyproject.toml (CRITICAL_CONFIG)" in patch.formatted_tail_diff


def test_ordinary_code_edit_preserves_prefix_and_stitches_at_tail() -> None:
    # Large realistic workspace baseline (e.g. 5,000 characters)
    system_prompt = "You are an autonomous engineering agent with full workspace access."
    workspace_tree = "\n".join(
        f"- src/module_{i}/handler_{i}.py (size: 2048 bytes)" for i in range(150)
    )

    bridge = SandboxContextCacheBridge(
        system_prompt=system_prompt,
        workspace_skeleton=workspace_tree,
    )
    initial_prefix_hash = bridge.current_prefix.content_hash
    probe = SandboxFsEventProbe()

    # Step 1: Agent modifies a single source file in sandbox
    probe.record_event(
        file_path="src/module_12/handler_12.py",
        kind=FileChangeKind.MODIFIED,
        diff_hunk="@@ -42,1 +42,2 @@\n+    return result.upper()",
    )

    conversation_body = "User: Optimize handler 12.\nAssistant: Patching handler 12 return statement."
    stitched_assembly = bridge.stitch_context(probe, conversation_body)

    # Invariant: Static prefix SHA-256 hash must be 100% IDENTICAL
    assert stitched_assembly.prefix_snapshot.content_hash == initial_prefix_hash
    assert stitched_assembly.tail_patch.invalidation_scope == InvalidationScope.TAIL_PATCH_ONLY

    # Structural check: Tail-only ordering
    prefix_text = bridge.current_prefix.full_prefix_text
    assert stitched_assembly.full_prompt_text.startswith(prefix_text)
    assert stitched_assembly.full_prompt_text.endswith(stitched_assembly.tail_patch.formatted_tail_diff)

    # Projected cache hit ratio must exceed 90% (around 95%+)
    assert stitched_assembly.cache_hit_ratio_projected >= 0.90

    # Step 2: Agent creates a new test file
    probe.record_event(
        file_path="tests/test_handler_12.py",
        kind=FileChangeKind.CREATED,
        diff_hunk="def test_handler_12(): assert True",
    )
    second_assembly = bridge.stitch_context(probe, conversation_body + "\nUser: Add test.")

    # Static prefix remains 100% preserved!
    assert second_assembly.prefix_snapshot.content_hash == initial_prefix_hash
    stats = bridge.cache_preservation_stats()
    assert stats["total_stitches"] == 2.0
    assert stats["preserved_stitches"] == 2.0
    assert stats["preservation_rate"] == 1.0


def test_critical_config_change_triggers_full_prefix_invalidation() -> None:
    bridge = SandboxContextCacheBridge(
        system_prompt="Base agent prompt.",
        workspace_skeleton="- package.json\n- src/index.ts",
    )
    old_hash = bridge.current_prefix.content_hash
    probe = SandboxFsEventProbe()

    # Modify critical dependency manifest in sandbox
    probe.record_event(
        file_path="package.json",
        kind=FileChangeKind.MODIFIED,
        diff_hunk="+    \"axios\": \"^1.7.0\"",
    )

    assembly = bridge.stitch_context(
        probe=probe,
        conversation_body="User: Install axios.",
        updated_system_prompt="Base agent prompt.",
        updated_workspace_skeleton="- package.json (modified)\n- src/index.ts",
    )

    # Must classify as full prefix invalidation
    assert assembly.tail_patch.invalidation_scope == InvalidationScope.FULL_PREFIX_INVALIDATION
    # Prefix hash must be re-anchored
    assert assembly.prefix_snapshot.content_hash != old_hash
    assert assembly.cache_hit_ratio_projected == 0.0


def test_empty_mutations_and_metric_tracking() -> None:
    bridge = SandboxContextCacheBridge(
        system_prompt="Prompt.",
        workspace_skeleton="Tree.",
    )
    probe = SandboxFsEventProbe()

    # No files modified during this turn
    assembly = bridge.stitch_context(probe, "User: What time is it?")
    assert assembly.tail_patch.events_count == 0
    assert assembly.tail_patch.invalidation_scope == InvalidationScope.TAIL_PATCH_ONLY
    assert assembly.cache_hit_ratio_projected > 0.0

    stats = bridge.cache_preservation_stats()
    assert stats["total_stitches"] == 1.0
    assert stats["preserved_stitches"] == 1.0
