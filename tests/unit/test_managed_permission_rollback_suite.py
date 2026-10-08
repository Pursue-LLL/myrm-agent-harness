"""Unit tests for Enterprise Role-Based Permission Templates, Checkpoint Rollback, and Connectors Hub Suite."""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.managed_permission_rollback import (
    ConnectorChannelType,
    ConnectorStatus,
    EnterprisePermissionPresetRegistry,
    EnterpriseRoleTemplate,
    ManagedConnectorsHub,
    PermissionActionRule,
    SessionCheckpointRollbackEngine,
)


def test_permission_presets_and_compliance_drift() -> None:
    registry = EnterprisePermissionPresetRegistry()
    presets = registry.list_presets()
    assert len(presets) == 4

    # 1. Auditor template structure
    auditor = registry.get_preset(EnterpriseRoleTemplate.AUDITOR)
    assert auditor.role == EnterpriseRoleTemplate.AUDITOR
    assert auditor.allow_shell_execution is False
    assert auditor.rules["TOOLS"] == PermissionActionRule.DENY

    # 2. Fully compliant evaluation
    report_compliant = registry.evaluate_compliance_drift(
        agent_id="agent_auditor_01",
        assigned_role=EnterpriseRoleTemplate.AUDITOR,
        active_rules={
            "TOOLS": PermissionActionRule.DENY,
            "FILES": PermissionActionRule.ALWAYS_ALLOW,
            "APIS": PermissionActionRule.DENY,
            "SENDS": PermissionActionRule.DENY,
        },
        active_allow_shell=False,
    )
    assert report_compliant.is_compliant is True
    assert report_compliant.drift_score == 0.0
    assert len(report_compliant.deviations) == 0

    # 3. Non-compliant evaluation with excessive permissions
    report_drift = registry.evaluate_compliance_drift(
        agent_id="agent_auditor_rogue",
        assigned_role=EnterpriseRoleTemplate.AUDITOR,
        active_rules={
            "TOOLS": PermissionActionRule.ALWAYS_ALLOW,  # excessive
            "FILES": PermissionActionRule.ALWAYS_ALLOW,
            "APIS": PermissionActionRule.ALWAYS_ALLOW,  # excessive
            "SENDS": PermissionActionRule.DENY,
        },
        active_allow_shell=True,  # excessive
    )
    assert report_drift.is_compliant is False
    assert report_drift.drift_score > 0.0
    assert len(report_drift.deviations) >= 3
    targets = {d.target for d in report_drift.deviations}
    assert "SHELL_EXECUTION" in targets
    assert "TOOLS" in targets
    assert "APIS" in targets


def test_session_checkpoint_and_rollback_lifecycle() -> None:
    engine = SessionCheckpointRollbackEngine()
    session_id = "sess_migration_999"

    initial_files = {
        "src/app.py": b"print('version 1.0')",
        "config.json": b'{"env": "staging"}',
    }
    initial_memory = {
        "intent": "Refactor authentication layer",
        "step": "1",
    }

    # 1. Create Checkpoint 1
    ckpt1 = engine.create_checkpoint(
        session_id=session_id,
        label="Pre-refactor clean state",
        files=initial_files,
        memory_state=initial_memory,
        active_role=EnterpriseRoleTemplate.FULL_STACK_DEVELOPER,
    )
    assert ckpt1.checkpoint_id.startswith("ckpt-")
    assert ckpt1.session_id == session_id
    assert len(ckpt1.file_snapshots) == 2

    # Query checkpoints
    history = engine.list_checkpoints(session_id)
    assert len(history) == 1
    assert history[0].checkpoint_id == ckpt1.checkpoint_id

    # 2. Simulate drift/unwanted mutations
    dirty_files = {
        "src/app.py": b"corrupted syntax error -- missing token",
        "config.json": b'{"env": "staging"}',  # unchanged
        "unwanted_temp.tmp": b"junk content",  # newly added
    }

    # 3. Execute rollback
    diff, restored_files, restored_memory = engine.rollback_to_checkpoint(
        checkpoint_id=ckpt1.checkpoint_id,
        current_files=dirty_files,
    )

    assert diff.checkpoint_id == ckpt1.checkpoint_id
    assert diff.session_id == session_id
    # Both modified src/app.py and added unwanted_temp.tmp should be captured in diff
    assert "src/app.py" in diff.modified_paths
    assert "unwanted_temp.tmp" in diff.modified_paths
    assert diff.reverted_files_count >= 2

    # Restored tree must match initial files exactly
    assert restored_files["src/app.py"] == b"print('version 1.0')"
    assert restored_files["config.json"] == b'{"env": "staging"}'
    assert "unwanted_temp.tmp" not in restored_files
    assert restored_memory["intent"] == "Refactor authentication layer"


def test_managed_connectors_hub() -> None:
    hub = ManagedConnectorsHub()

    # 1. Register Discord connector
    conn_discord = hub.register_connector(
        connector_id="discord-bot-ops",
        channel_type=ConnectorChannelType.DISCORD,
        display_name="Enterprise Ops Discord Relay",
        account_identifier="corp_discord_srv_1",
        token_lifetime_seconds=1800.0,
    )
    assert conn_discord.status == ConnectorStatus.ACTIVE
    assert conn_discord.channel_type == ConnectorChannelType.DISCORD

    # 2. Heartbeat update
    hb = hub.record_heartbeat("discord-bot-ops")
    assert hb is not None
    assert hb.status == ConnectorStatus.ACTIVE

    # 3. Transition status to DEGRADED
    updated = hub.update_status("discord-bot-ops", ConnectorStatus.DEGRADED)
    assert updated is not None
    assert updated.status == ConnectorStatus.DEGRADED

    # 4. List connectors
    conns = hub.list_connectors()
    assert len(conns) == 1
    assert conns[0].connector_id == "discord-bot-ops"

    # 5. Token expiry detection
    _expired_conn = hub.register_connector(
        connector_id="github-pat-ci",
        channel_type=ConnectorChannelType.GITHUB,
        display_name="GitHub CI Runner",
        account_identifier="org/repo",
        token_lifetime_seconds=-10.0,  # Expired in past
    )
    time.sleep(0.01)
    hb_expired = hub.record_heartbeat("github-pat-ci")
    assert hb_expired is not None
    assert hb_expired.status == ConnectorStatus.EXPIRED
