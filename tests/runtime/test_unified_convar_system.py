"""Unit tests for Source-engine style declarative Convar system and scoped inheritance.

Tests benchmarked against Can Bölük's Harness Playbook Chapter 3.3 Control Plane Convars:
1. Definition registration, type coercion, and numerical boundary validation.
2. Hierarchical scoped inheritance (Global -> Session -> Subagent) with local isolation.
3. Dirty-state tracking and change notification callback dispatch.
4. READ_ONLY mutability barriers.
5. Standard .cfg format loading and serialization filtering.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.convar import (
    ConvarDefinition,
    ConvarFlags,
    ConvarRegistry,
    ConvarType,
    ScopedConvarContext,
)


def create_sample_registry() -> ConvarRegistry:
    """Helper creating a standard test registry with mixed-type Convars."""
    reg = ConvarRegistry()

    reg.register(
        ConvarDefinition(
            name="agent_temperature",
            convar_type=ConvarType.FLOAT,
            default_value="0.7",
            help_text="Sampling temperature for primary agent",
            flags=ConvarFlags.ARCHIVE | ConvarFlags.REPLICATED,
            min_val=0.0,
            max_val=2.0,
        )
    )
    reg.register(
        ConvarDefinition(
            name="agent_max_tokens",
            convar_type=ConvarType.INT,
            default_value="4096",
            help_text="Max completion tokens",
            flags=ConvarFlags.ARCHIVE,
            min_val=128,
            max_val=32768,
        )
    )
    reg.register(
        ConvarDefinition(
            name="sandbox_auto_clean",
            convar_type=ConvarType.BOOL,
            default_value="1",
            help_text="Clean sandbox container on exit",
            flags=ConvarFlags.SESSION_ONLY,
        )
    )
    reg.register(
        ConvarDefinition(
            name="system_cluster_id",
            convar_type=ConvarType.STR,
            default_value="cluster-prod-01",
            help_text="Immutable cluster identifier",
            flags=ConvarFlags.READ_ONLY,
        )
    )
    return reg


def test_convar_registry_type_coercion_and_bounds() -> None:
    """Test primitive type conversion and boundary guardrails."""
    reg = create_sample_registry()
    defn_temp = reg.get_definition("agent_temperature")
    assert defn_temp is not None

    # 1. Valid float conversion
    raw_str, typed_val = reg.coerce_value(defn_temp, "1.25")
    assert raw_str == "1.25"
    assert typed_val == 1.25

    # 2. Out of bounds float
    with pytest.raises(ValueError) as err_high:
        reg.coerce_value(defn_temp, "2.5")
    assert "exceeds maximum 2.0" in str(err_high.value)

    with pytest.raises(ValueError) as err_low:
        reg.coerce_value(defn_temp, "-0.1")
    assert "below minimum 0.0" in str(err_low.value)

    # 3. Boolean representations
    defn_bool = reg.get_definition("sandbox_auto_clean")
    assert defn_bool is not None
    assert reg.coerce_value(defn_bool, "true")[1] is True
    assert reg.coerce_value(defn_bool, "0")[1] is False
    assert reg.coerce_value(defn_bool, "off")[1] is False


def test_scoped_convar_inheritance_and_isolation() -> None:
    """Test hierarchical scope inheritance (Global -> Session -> Subagent) with local override."""
    reg = create_sample_registry()

    # Create 3-level scope tree
    global_scope = ScopedConvarContext(scope_name="global", registry=reg)
    session_scope = global_scope.fork_child("session_101")
    subagent_scope = session_scope.fork_child("subagent_worker_a")

    # 1. Initial lookup traverses up to registry default
    assert global_scope.get_typed("agent_temperature") == 0.7
    assert session_scope.get_typed("agent_temperature") == 0.7
    assert subagent_scope.get_typed("agent_temperature") == 0.7

    # 2. Modify at session level -> inherited by subagent, global untouched
    session_scope.set("agent_temperature", 0.4)
    assert global_scope.get_typed("agent_temperature") == 0.7
    assert session_scope.get_typed("agent_temperature") == 0.4
    assert subagent_scope.get_typed("agent_temperature") == 0.4

    # 3. Modify at subagent level -> local override, session and global untouched
    subagent_scope.set("agent_temperature", 0.1)
    assert global_scope.get_typed("agent_temperature") == 0.7
    assert session_scope.get_typed("agent_temperature") == 0.4
    assert subagent_scope.get_typed("agent_temperature") == 0.1


def test_convar_dirty_tracking_and_listeners() -> None:
    """Test dirty key tracking and change notification callbacks."""
    reg = create_sample_registry()
    ctx = ScopedConvarContext(scope_name="test_scope", registry=reg)

    events: list[tuple[str, str, str, str | int | float | bool]] = []
    ctx.add_listener(lambda name, old_r, new_r, new_t: events.append((name, old_r, new_r, new_t)))

    assert ctx.is_dirty("agent_max_tokens") is False

    ctx.set("agent_max_tokens", 8192)
    assert ctx.is_dirty("agent_max_tokens") is True
    assert len(events) == 1
    assert events[0] == ("agent_max_tokens", "4096", "8192", 8192)

    # Clearing dirty flag
    ctx.clear_dirty("agent_max_tokens")
    assert ctx.is_dirty("agent_max_tokens") is False


def test_convar_read_only_protection() -> None:
    """Test that READ_ONLY Convars reject mutations after initialization."""
    reg = create_sample_registry()
    ctx = ScopedConvarContext(scope_name="test_scope", registry=reg)

    # First set in local context
    ctx.set("system_cluster_id", "cluster-custom-01")
    assert ctx.get_raw("system_cluster_id") == "cluster-custom-01"

    # Subsequent mutation should be blocked
    with pytest.raises(PermissionError) as exc_info:
        ctx.set("system_cluster_id", "cluster-hacked")
    assert "READ_ONLY and cannot be mutated" in str(exc_info.value)


def test_convar_cfg_load_and_export() -> None:
    """Test loading from and exporting to Source-engine standard .cfg configuration format."""
    reg = create_sample_registry()
    ctx = ScopedConvarContext(scope_name="session_cfg", registry=reg)

    cfg_input = """
    # Subagent Configuration Preset
    agent_temperature "0.2"
    agent_max_tokens 16384
    sandbox_auto_clean "false"
    # Commented line should be ignored
    // Another comment format
    unknown_cvar "ignored"
    """

    applied = ctx.load_cfg(cfg_input)
    assert applied == 3
    assert ctx.get_typed("agent_temperature") == 0.2
    assert ctx.get_typed("agent_max_tokens") == 16384
    assert ctx.get_typed("sandbox_auto_clean") is False

    # Exporting with ARCHIVE flag filter (only agent_temperature and agent_max_tokens carry ARCHIVE)
    exported = ctx.export_cfg(flag_filter=ConvarFlags.ARCHIVE)
    assert 'agent_temperature "0.2"' in exported
    assert 'agent_max_tokens "16384"' in exported
    assert "sandbox_auto_clean" not in exported  # carries SESSION_ONLY, not ARCHIVE
