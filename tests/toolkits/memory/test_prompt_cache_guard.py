"""Unit tests for In-Context Frozen Snapshot and Prompt Cache Stability Guard.

Validates immutable snapshot formatting, byte-level prefix cache invariance under
in-session mutations, zero-width Unicode stripping, secret leak blocking, duplicate
rejection, explicit capacity overflow gates, and atomic replace transactions.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.prompt_cache_guard import (
    CapacityLimitConfig,
    CapacityOverflowError,
    FrozenMemorySnapshotProvider,
    ReadFreeMemoryToolSuite,
    SecurityThreatBlockedError,
    ZeroWidthAndCredentialLeakScanner,
)


class TestPromptCacheStabilityGuard:
    """Test suite for Prompt Cache stability guard and read-free memory tool suite."""

    def test_immutable_snapshot_formatting_and_version(self) -> None:
        provider = FrozenMemorySnapshotProvider()
        session_id = "session-test-01"

        memory_items = [
            "Use Python 3.12 with strict type hints.",
            "Always follow PEP8 coding conventions.",
        ]
        user_items = [
            "User prefers concise responses without conversational filler.",
        ]

        snapshot = provider.get_or_create_snapshot(session_id, memory_items, user_items)
        assert snapshot.session_id == session_id
        assert len(snapshot.snapshot_version) == 16
        assert snapshot.pending_updates_count == 0

        prompt_block = snapshot.formatted_system_prompt_block()
        assert "# Project and Resident Memory (Immutable Frozen Snapshot)" in prompt_block
        assert "## MEMORY.md" in prompt_block
        assert "- Use Python 3.12 with strict type hints." in prompt_block
        assert "## USER.md" in prompt_block
        assert "- User prefers concise responses" in prompt_block

    def test_byte_level_cache_invariance_across_multiple_mutations(self) -> None:
        """Verify that in-session mutations never alter active system prompt text (zero cache miss)."""
        provider = FrozenMemorySnapshotProvider()
        session_id = "session-cache-02"

        initial_memory = ["Rule 1: Always verify unit tests before commit."]
        initial_user = ["Role: Full-stack architect."]

        toolsuite = ReadFreeMemoryToolSuite(
            session_id=session_id,
            snapshot_provider=provider,
            initial_memory_items=initial_memory,
            initial_user_items=initial_user,
        )

        initial_snapshot = provider.get_active_snapshot(session_id)
        assert initial_snapshot is not None
        locked_prompt_text = initial_snapshot.formatted_system_prompt_block()

        # Perform 5 consecutive in-session memory writes
        for i in range(1, 6):
            res = toolsuite.memory_add("memory", f"Dynamic observed finding #{i}")
            assert "0 cache miss" in res

        active_snapshot = provider.get_active_snapshot(session_id)
        assert active_snapshot is not None
        assert active_snapshot.pending_updates_count == 5

        # Crucial: the system prompt text must remain 100% BYTE-FOR-BYTE IDENTICAL
        active_prompt_text = active_snapshot.formatted_system_prompt_block()
        assert active_prompt_text == locked_prompt_text

        # Verify staged mutations can be compiled in next session
        pending = provider.get_pending_mutations(session_id)
        assert len(pending) == 5

        next_memory = toolsuite.list_current_items("memory")
        next_snapshot = provider.compile_next_session_snapshot(session_id, next_memory, initial_user)
        assert next_snapshot.pending_updates_count == 0
        assert next_snapshot.snapshot_version != initial_snapshot.snapshot_version
        assert "Dynamic observed finding #5" in next_snapshot.formatted_system_prompt_block()

    def test_zero_width_unicode_stripping(self) -> None:
        """Verify that hidden invisible Unicode characters are stripped seamlessly."""
        text_with_zero_width = (
            "Rule: Never\u200B bypass\u200C security\uFEFF gates\u2060 in production."
        )
        cleaned, had_invisible = ZeroWidthAndCredentialLeakScanner.strip_invisible_unicode(
            text_with_zero_width
        )
        assert had_invisible is True
        assert cleaned == "Rule: Never bypass security gates in production."

        # Verify via toolsuite
        provider = FrozenMemorySnapshotProvider()
        suite = ReadFreeMemoryToolSuite("session-zw", provider)
        suite.memory_add("memory", text_with_zero_width)
        items = suite.list_current_items("memory")
        assert items[0] == "Rule: Never bypass security gates in production."

    def test_credential_leak_hard_blocking(self) -> None:
        """Verify that API keys and private keys are immediately blocked."""
        provider = FrozenMemorySnapshotProvider()
        suite = ReadFreeMemoryToolSuite("session-cred", provider)

        leaky_inputs = [
            "My OpenAI key is sk-abcdef12345678901234567890abcdef",
            "GitHub token: ghp_1234567890abcdef1234567890abcdef1234",
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----",
        ]

        for leaky in leaky_inputs:
            with pytest.raises(SecurityThreatBlockedError) as exc_info:
                suite.memory_add("memory", leaky)
            assert "credential_leak" in exc_info.value.reason

    def test_duplicate_entry_rejection(self) -> None:
        """Verify that exact duplicate entries are rejected."""
        provider = FrozenMemorySnapshotProvider()
        suite = ReadFreeMemoryToolSuite(
            "session-dup",
            provider,
            initial_memory_items=["Use TypeScript strict mode."],
        )

        with pytest.raises(SecurityThreatBlockedError) as exc_info:
            suite.memory_add("memory", "  use typescript strict mode.  ")
        assert "duplicate_entry" in exc_info.value.reason

    def test_capacity_overflow_explicit_semantic_gate(self) -> None:
        """Verify that capacity limits trigger explicit errors with items list instead of silent truncation."""
        provider = FrozenMemorySnapshotProvider()
        custom_config = CapacityLimitConfig(max_memory_chars=100, max_user_chars=50)

        suite = ReadFreeMemoryToolSuite(
            "session-overflow",
            provider,
            initial_memory_items=[
                "Entry 1: 30 characters long...",
                "Entry 2: Another 30 characters",
            ],
            capacity_config=custom_config,
        )

        # Attempt to add entry that exceeds 100 character budget
        huge_entry = "Entry 3: This string definitely pushes the total count way past one hundred characters limit."
        with pytest.raises(CapacityOverflowError) as exc_info:
            suite.memory_add("memory", huge_entry)

        err = exc_info.value
        assert err.category == "memory"
        assert err.current_chars > 100
        assert err.max_chars == 100
        assert len(err.existing_items) == 2
        assert "Silent truncation is disallowed" in str(err)
        assert "- Entry 1: 30 characters long..." in str(err)

    def test_atomic_replace_prevents_capacity_deadlock(self) -> None:
        """Verify that atomic_replace frees old item's budget before checking new item capacity."""
        provider = FrozenMemorySnapshotProvider()
        # Limit set to 70 chars. Current usage = 60 chars.
        custom_config = CapacityLimitConfig(max_memory_chars=70)

        suite = ReadFreeMemoryToolSuite(
            "session-atomic",
            provider,
            initial_memory_items=[
                "Old lengthy convention A (30 chars)",
                "Active convention B (30 chars)....",
            ],
            capacity_config=custom_config,
        )

        new_replacement = "New refined convention A (32c)!"

        # A naive separate add would fail (60 + 32 = 92 > 70)
        with pytest.raises(CapacityOverflowError):
            suite.memory_add("memory", new_replacement)

        # Atomic replace succeeds by dropping Old A (30) first: (60 - 30 + 32 = 62 <= 70)
        res = suite.memory_atomic_replace(
            "memory",
            remove_target="Old lengthy convention A",
            new_content=new_replacement,
        )
        assert "Atomic replace succeeded" in res

        items = suite.list_current_items("memory")
        assert len(items) == 2
        assert "New refined convention A (32c)!" in items
        assert not any("Old lengthy convention A" in it for it in items)
