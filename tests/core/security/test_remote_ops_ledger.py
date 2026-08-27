"""Unit tests for RemoteOpsActionRecord and derive_recovery_hint.

Validates fingerprinting, recovery clue derivation, and audit record integrity.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.audit import SecurityDecision, record_decision, get_audit_entries, reset_audit_log
from myrm_agent_harness.core.security.remote_ops_ledger import (
    ActionRecoveryHint,
    RemoteOpsActionRecord,
    compute_action_fingerprint,
    derive_recovery_hint,
)


def test_compute_action_fingerprint_deterministic():
    args_1 = {"command": "systemctl stop nginx", "timeout": 30}
    args_2 = {"timeout": 30, "command": "systemctl stop nginx"}
    
    fp_1 = compute_action_fingerprint("shell_exec", args_1)
    fp_2 = compute_action_fingerprint("shell_exec", args_2)
    
    assert fp_1 == fp_2
    assert len(fp_1) == 16


def test_derive_recovery_hint_service_stop():
    args = {"command": "sudo systemctl stop nginx"}
    hint = derive_recovery_hint("shell_exec", args)
    assert hint is not None
    assert hint.recovery_type == "service_restart"
    assert hint.recovery_command == "systemctl start nginx"
    assert "Restart stopped system service" in hint.description
    assert hint.is_automated is True


def test_derive_recovery_hint_service_start():
    args = {"command": "service redis start"}
    hint = derive_recovery_hint("shell_exec", args)
    assert hint is not None
    assert hint.recovery_type == "service_stop"
    assert hint.recovery_command == "systemctl stop redis"
    assert hint.is_automated is True


def test_derive_recovery_hint_process_kill():
    args = {"command": "pkill -9 python"}
    hint = derive_recovery_hint("shell_exec", args)
    assert hint is not None
    assert hint.recovery_type == "manual_check"
    assert hint.recovery_command is None
    assert "Verify and relaunch" in hint.description


def test_derive_recovery_hint_file_backup():
    args = {"path": "/workspace/config.json"}
    hint = derive_recovery_hint("file_edit", args, backup_path="/tmp/backup_config.json")
    assert hint is not None
    assert hint.recovery_type == "file_restore"
    assert hint.recovery_command == "cp -p '/tmp/backup_config.json' '/workspace/config.json'"
    assert hint.is_automated is True


def test_remote_ops_action_record_serialization():
    hint = ActionRecoveryHint(
        recovery_type="service_restart",
        recovery_command="systemctl start nginx",
        description="Restart nginx",
        is_automated=True,
    )
    record = RemoteOpsActionRecord(
        action_id="act-123",
        device_id="edge-node-01",
        tool_name="shell_exec",
        action_type="service_stop",
        fingerprint="abcd1234efgh5678",
        status="success",
        exit_code=0,
        recovery_hint=hint,
    )
    d = record.to_dict()
    assert d["action_id"] == "act-123"
    assert d["device_id"] == "edge-node-01"
    assert d["recovery_hint"]["recovery_command"] == "systemctl start nginx"


def test_audit_record_decision_with_device_and_recovery():
    reset_audit_log()
    record_decision(
        "shell_exec",
        "ALLOW",
        "Routine maintenance",
        device_id="node-99",
        recovery_hint="systemctl start nginx",
    )
    entries = get_audit_entries()
    assert len(entries) == 1
    assert entries[0].device_id == "node-99"
    assert entries[0].recovery_hint == "systemctl start nginx"
    d = entries[0].to_dict()
    assert d["device_id"] == "node-99"
    assert d["recovery_hint"] == "systemctl start nginx"
