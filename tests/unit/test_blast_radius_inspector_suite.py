"""Unit tests for Agent Action Surface Blast Radius Static Inspector and Guard Attribution Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.blast_radius_inspector.guard_attribution import (
    GuardAttributionEngine,
)
from myrm_agent_harness.core.security.blast_radius_inspector.kill_switch import (
    GlobalActionKillSwitch,
)
from myrm_agent_harness.core.security.blast_radius_inspector.static_inspector import (
    ActionSurfaceStaticInspector,
)
from myrm_agent_harness.core.security.blast_radius_inspector.types import (
    ActionSurfaceDimension,
    AtomicActionCategory,
    DangerTier,
    GuardStatus,
)


def test_action_surface_static_inspector_4d_metrics() -> None:
    inspector = ActionSurfaceStaticInspector(critical_exposure_threshold=60.0)

    tools = ["browse_web", "write_file", "shell_exec"]
    file_scopes = ["/workspace", "/tmp"]
    apis = ["https://api.github.com/v3"]
    sends = ["email_dispatcher"]
    plugins = ["community-telegram-bot"]

    report, sinks = inspector.inspect_profile(
        tools=tools,
        declared_file_scopes=file_scopes,
        declared_api_endpoints=apis,
        declared_send_channels=sends,
        installed_plugins=plugins,
    )

    # Verify counts
    assert report.total_tools_count == 3
    assert report.total_files_scope_count == 2
    assert report.total_apis_count == 1
    assert report.total_sends_count == 1

    # Verify action category breakdown
    assert report.action_breakdown[AtomicActionCategory.BROWSE.value] == 1
    assert report.action_breakdown[AtomicActionCategory.WRITE_FILE.value] >= 2
    assert report.action_breakdown[AtomicActionCategory.EMAIL.value] == 1
    assert report.action_breakdown[AtomicActionCategory.MUTATE_SYSTEM.value] >= 1

    # Verify two-tier risk stratification
    assert report.reachable_verified_count >= 6
    assert report.install_liability_count == 1

    # Check that plugin liability has DangerTier.INSTALL_LIABILITY
    plugin_sinks = [s for s in sinks if s.danger_tier == DangerTier.INSTALL_LIABILITY]
    assert len(plugin_sinks) == 1
    assert "community-telegram-bot" in plugin_sinks[0].sink_identifier


def test_action_surface_pre_admission_gate() -> None:
    inspector = ActionSurfaceStaticInspector(critical_exposure_threshold=30.0)

    # 1. Low blast radius profile passes pre-admission
    safe_report, _ = inspector.inspect_profile(
        tools=["browse_web"],
        declared_file_scopes=[],
        declared_api_endpoints=[],
        declared_send_channels=[],
        installed_plugins=[],
    )
    assert safe_report.pre_admission_allowed is True
    assert safe_report.admission_rejection_reason is None

    # 2. Excessive agency profile is rejected
    excessive_report, _ = inspector.inspect_profile(
        tools=["browse_web", "shell_exec", "write_file", "delete_file"],
        declared_file_scopes=["/etc", "/var", "/root"],
        declared_api_endpoints=["https://webhook.site/1", "https://api.slack.com"],
        declared_send_channels=["email_all", "post_twitter"],
        installed_plugins=["plugin_a", "plugin_b"],
    )
    assert excessive_report.pre_admission_allowed is False
    assert "Pre-admission rejected" in (excessive_report.admission_rejection_reason or "")


def test_guard_attribution_matrix_and_auto_repair() -> None:
    inspector = ActionSurfaceStaticInspector()
    _report, sinks = inspector.inspect_profile(
        tools=["write_file"],
        declared_file_scopes=["/workspace"],
        declared_api_endpoints=["https://api.openai.com"],
        declared_send_channels=["email_sender"],
    )

    # Configure guard for SENDS only
    engine = GuardAttributionEngine()
    active_guards = {
        ActionSurfaceDimension.SENDS.value: "HITL_HUMAN_IN_THE_LOOP",
    }

    attributed_items = engine.attribute_guards(sinks, active_guards)

    # Verify attribution statuses
    sends_items = [i for i in attributed_items if i.sink.dimension == ActionSurfaceDimension.SENDS]
    assert len(sends_items) >= 1
    assert sends_items[0].guard_status == GuardStatus.GUARD_ATTRIBUTED
    assert sends_items[0].assigned_guard_name == "HITL_HUMAN_IN_THE_LOOP"

    # Verify unguarded sinks exist
    unguarded = [i for i in attributed_items if i.guard_status == GuardStatus.UNGUARDED_CRITICAL]
    assert len(unguarded) >= 1

    # Synthesize auto-repair policy patches
    patches = engine.synthesize_repair_patches(attributed_items)
    assert len(patches) == len(unguarded)

    # Check generated patch structure
    patch_types = {p.injected_guard_type for p in patches}
    assert "PATH_RESTRICTION" in patch_types or "DOMAIN_ALLOWLIST" in patch_types


def test_global_action_kill_switch_behavior() -> None:
    kill_switch = GlobalActionKillSwitch()
    assert kill_switch.get_state().is_engaged is False
    assert kill_switch.is_action_blocked(ActionSurfaceDimension.SENDS) is False

    # Engage kill switch
    state = kill_switch.engage(operator_identity="admin@myrmidon.ai", reason="Emergency containment")
    assert state.is_engaged is True
    assert kill_switch.is_action_blocked(ActionSurfaceDimension.SENDS) is True
    assert kill_switch.is_action_blocked(ActionSurfaceDimension.APIS) is True
    assert kill_switch.is_action_blocked(ActionSurfaceDimension.FILES) is True
    assert kill_switch.is_action_blocked(ActionSurfaceDimension.TOOLS) is True

    # Disengage kill switch
    restored = kill_switch.disengage()
    assert restored.is_engaged is False
    assert kill_switch.is_action_blocked(ActionSurfaceDimension.SENDS) is False
