"""Unit tests for SandboxMountSecurityGate in myrm_agent_harness.

Tests cover:
- MountSpec & MountValidationResult immutable data structures
- Empty and null byte path detection
- Blocked device paths (CON, NUL, COM*, \\\\.\\*, /dev/*)
- Dangerous system/user roots (/etc, /proc, ~/.ssh, ~/.aws)
- Path traversal (..)
- Symlink escape detection
- Boundary enclosure verification (with case-insensitivity on macOS / Windows)
- Mode least privilege enforcement (RO vs RW)
- validate_and_sanitize_mounts batch processing & deduplication
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.core.security.types import AccessRoot
from myrm_agent_harness.toolkits.code_execution.sandbox.mount_security_gate import (
    MountMode,
    MountSpec,
    MountValidationResult,
    MountViolationType,
    validate_and_sanitize_mounts,
    validate_mount_spec,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.policy_bridge import (
    build_sandbox_policy_from_path_policy,
)


class TestMountSpecAndValidationTypes:
    def test_mount_spec_properties(self) -> None:
        spec_rw = MountSpec(source_path="/tmp/test", mode=MountMode.RW, label="test_rw")
        assert spec_rw.is_writable is True
        assert spec_rw.source_path == "/tmp/test"
        assert spec_rw.target_path == ""

        spec_ro = MountSpec(source_path="/tmp/test", mode=MountMode.RO, label="test_ro")
        assert spec_ro.is_writable is False

    def test_frozen_dataclass(self) -> None:
        spec = MountSpec(source_path="/tmp/test")
        with pytest.raises(AttributeError):
            spec.source_path = "/tmp/other"  # type: ignore[misc]


class TestMountValidationRules:
    def test_empty_path_rejection(self) -> None:
        spec = MountSpec(source_path="   ")
        result = validate_mount_spec(spec)
        assert result.is_valid is False
        assert result.violation_type == MountViolationType.EMPTY_PATH

    def test_null_byte_rejection(self) -> None:
        spec = MountSpec(source_path="/workspace/test\0/escaped")
        result = validate_mount_spec(spec)
        assert result.is_valid is False
        assert result.violation_type == MountViolationType.NULL_BYTE

    def test_blocked_device_paths(self) -> None:
        devices = [
            "CON",
            "NUL",
            "COM1",
            "\\\\.\\PhysicalDrive0",
            "/dev/sda",
            "dev/urandom",
        ]
        for dev in devices:
            spec = MountSpec(source_path=dev)
            result = validate_mount_spec(spec)
            assert result.is_valid is False
            assert result.violation_type == MountViolationType.BLOCKED_DEVICE

    def test_dangerous_paths_rejection(self) -> None:
        dangerous = ["/etc", "/etc/passwd", "~/.ssh", "~/.ssh/id_rsa", "~/.aws"]
        for p in dangerous:
            spec = MountSpec(source_path=p)
            result = validate_mount_spec(spec)
            assert result.is_valid is False
            assert result.violation_type == MountViolationType.DANGEROUS_PATH

    def test_device_paths_rejection(self) -> None:
        devices = ["/proc/kcore", "/dev/null", "/dev/zero"]
        for p in devices:
            spec = MountSpec(source_path=p)
            result = validate_mount_spec(spec)
            assert result.is_valid is False
            assert result.violation_type == MountViolationType.BLOCKED_DEVICE

    def test_dangerous_path_override(self) -> None:
        # When explicit override is enabled (e.g. testing)
        spec = MountSpec(source_path="/etc")
        result = validate_mount_spec(spec, allow_dangerous_override=True)
        assert result.is_valid is True

    def test_boundary_enclosure_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sub = os.path.join(tmpdir, "subdir")
            os.makedirs(sub, exist_ok=True)

            spec = MountSpec(source_path=sub)
            result = validate_mount_spec(spec, allowed_boundaries=(tmpdir,))
            assert result.is_valid is True
            assert result.sanitized_spec is not None
            assert result.sanitized_spec.source_path == os.path.normpath(sub)

    def test_boundary_enclosure_failure(self) -> None:
        with (
            tempfile.TemporaryDirectory() as boundary_dir,
            tempfile.TemporaryDirectory() as outside_dir,
        ):
            spec = MountSpec(source_path=outside_dir)
            result = validate_mount_spec(spec, allowed_boundaries=(boundary_dir,))
            assert result.is_valid is False
            assert result.violation_type == MountViolationType.UNAUTHORIZED_BOUNDARY

    def test_symlink_escape_detection(self) -> None:
        with (
            tempfile.TemporaryDirectory() as ws,
            tempfile.TemporaryDirectory() as outside,
        ):
            secret_file = os.path.join(outside, "secret.txt")
            with open(secret_file, "w") as f:
                f.write("secret")

            link_path = os.path.join(ws, "link_to_secret")
            os.symlink(secret_file, link_path)

            spec = MountSpec(source_path=link_path)
            result = validate_mount_spec(spec, allowed_boundaries=(ws,))
            assert result.is_valid is False
            assert result.violation_type == MountViolationType.SYMLINK_ESCAPE

    def test_permission_violation_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = MountSpec(source_path=tmpdir, mode=MountMode.RO)
            result = validate_mount_spec(spec, require_write=True)
            assert result.is_valid is False
            assert result.violation_type == MountViolationType.PERMISSION_VIOLATION

    def test_pending_target_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pending_child = os.path.join(tmpdir, "new_folder", "nested_dir")
            spec = MountSpec(source_path=pending_child)
            result = validate_mount_spec(spec, allowed_boundaries=(tmpdir,))
            assert result.is_valid is True
            assert result.sanitized_spec is not None

    def test_boundary_enclosure_exception_handling(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.sandbox.mount_security_gate import (
            _is_path_enclosed_in_boundary,
        )

        assert _is_path_enclosed_in_boundary("\0invalid", "/tmp") is False

    def test_unc_path_rejection(self) -> None:
        unc_paths = [
            r"\\evil-smb.com\share",
            r"\\192.168.1.100\payload",
            "//evil-smb.com/share",
        ]
        for p in unc_paths:
            spec = MountSpec(source_path=p)
            result = validate_mount_spec(spec)
            assert result.is_valid is False
            assert result.violation_type == MountViolationType.PATH_TRAVERSAL

    def test_target_path_null_byte_and_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            # Null byte in target
            spec1 = MountSpec(source_path=ws, target_path="/app/cache\0/etc")
            result1 = validate_mount_spec(spec1)
            assert result1.is_valid is False
            assert result1.violation_type == MountViolationType.NULL_BYTE

            # Traversal in target
            spec2 = MountSpec(source_path=ws, target_path="/app/../../../etc/shadow")
            result2 = validate_mount_spec(spec2)
            assert result2.is_valid is False
            assert result2.violation_type == MountViolationType.PATH_TRAVERSAL

    def test_target_path_prohibited_container_roots(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            prohibited_targets = [
                "/bin",
                "/usr/bin",
                "/sbin",
                "/etc/ld.so.preload",
                "/etc/shadow",
                "/etc/passwd",
                "/proc",
                "/sys",
                "/dev",
            ]
            for target in prohibited_targets:
                spec = MountSpec(source_path=ws, target_path=target)
                result = validate_mount_spec(spec)
                assert result.is_valid is False
                assert result.violation_type == MountViolationType.DANGEROUS_PATH

    def test_target_collision_detection_in_batch(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            sub1 = os.path.join(ws, "sub1")
            sub2 = os.path.join(ws, "sub2")
            os.makedirs(sub1, exist_ok=True)
            os.makedirs(sub2, exist_ok=True)

            mounts = [
                MountSpec(
                    source_path=sub1, target_path="/workspace/data", mode=MountMode.RW
                ),
                MountSpec(
                    source_path=sub2, target_path="/workspace/data", mode=MountMode.RO
                ),  # collision
            ]

            sanitized = validate_and_sanitize_mounts(mounts)
            assert len(sanitized) == 1
            assert sanitized[0].source_path == os.path.normpath(sub1)

    def test_resolution_depth_limit(self) -> None:
        deep_path = "/tmp" + "/a" * 40
        with pytest.raises(ValueError, match="depth limit"):
            from myrm_agent_harness.toolkits.code_execution.sandbox.mount_security_gate import (
                _resolve_physical_path,
            )

            _resolve_physical_path(deep_path, max_depth=10)


class TestBatchMountSanitizationAndPolicyBridge:
    def test_validate_and_sanitize_mounts_batch(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            sub1 = os.path.join(ws, "sub1")
            sub2 = os.path.join(ws, "sub2")
            os.makedirs(sub1, exist_ok=True)
            os.makedirs(sub2, exist_ok=True)

            mounts = [
                MountSpec(source_path=sub1, mode=MountMode.RW),
                MountSpec(source_path=sub2, mode=MountMode.RO),
                MountSpec(source_path="/etc/shadow"),  # dangerous -> rejected
                MountSpec(source_path="CON"),  # device -> rejected
                MountSpec(source_path=sub1, mode=MountMode.RW),  # duplicate
            ]

            sanitized = validate_and_sanitize_mounts(mounts)
            assert len(sanitized) == 2
            paths = [s.source_path for s in sanitized]
            assert os.path.normpath(sub1) in paths
            assert os.path.normpath(sub2) in paths

    def test_policy_bridge_integration(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            extra_valid = os.path.join(ws, "extra")
            os.makedirs(extra_valid, exist_ok=True)

            access_roots = (
                AccessRoot(path=extra_valid, writable=True, source="test"),
                AccessRoot(
                    path="/etc/passwd", writable=True, source="malicious"
                ),  # rejected
            )

            policy = build_sandbox_policy_from_path_policy(
                work_dir=ws,
                access_roots=access_roots,
                extra_writable=("/dev/null",),  # rejected
            )

            assert os.path.normpath(ws) in policy.writable_paths
            assert os.path.normpath(extra_valid) in policy.writable_paths
            assert "/etc/passwd" not in policy.writable_paths
            assert "/dev/null" not in policy.writable_paths
