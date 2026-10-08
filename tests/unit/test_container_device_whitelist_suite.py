"""Unit tests for Sandbox Container Device Whitelist Hardening
and Block Device Strip Suite.

Verifies strict virtual pseudo-device allowlisting, physical block device stripping,
host hardware node stripping, and Docker cgroup device rule generation.
Strict typing applied: No `Any` types allowed. Enforced under 400 lines limit.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.device_whitelist import (
    STANDARD_VIRTUAL_DEVICES,
    ContainerDevicePolicyConfig,
    ContainerDeviceSanitizer,
    ContainerDeviceWhitelistFacade,
    DeviceSanitizeAction,
    DeviceType,
)


def test_standard_virtual_devices_allowed() -> None:
    sanitizer = ContainerDeviceSanitizer()

    # 6 core pseudo-devices aligned with CodePilot L295-306
    standard_paths = [
        "/dev/null",
        "/dev/zero",
        "/dev/full",
        "/dev/random",
        "/dev/urandom",
        "/dev/tty",
        "/dev/ptmx",
        "/dev/pts/0",
        "/dev/pts/1",
    ]

    for path in standard_paths:
        res = sanitizer.inspect_device(path)
        assert res.action == DeviceSanitizeAction.ALLOW, f"Expected {path} to be ALLOWED"
        assert res.matched_rule == "ALLOWED_VIRTUAL_DEVICE"
        assert res.device_type == DeviceType.CHAR


def test_physical_block_devices_stripped() -> None:
    sanitizer = ContainerDeviceSanitizer()

    block_devices = [
        "/dev/sda",
        "/dev/sda1",
        "/dev/sdb2",
        "/dev/nvme0n1",
        "/dev/nvme0n1p1",
        "/dev/vda",
        "/dev/hda",
        "/dev/loop0",
        "/dev/mmcblk0p1",
        "/dev/dm-0",
    ]

    for bdev in block_devices:
        res = sanitizer.inspect_device(bdev)
        assert res.action == DeviceSanitizeAction.STRIP, f"Expected {bdev} to be STRIPPED"
        assert res.matched_rule == "STRIPPED_PHYSICAL_BLOCK_DEVICE"
        assert res.device_type == DeviceType.BLOCK
        assert "physical/virtual block device" in res.reason


def test_host_hardware_devices_stripped() -> None:
    sanitizer = ContainerDeviceSanitizer()

    dangerous_devices = [
        "/dev/mem",
        "/dev/kmem",
        "/dev/kmsg",
        "/dev/port",
        "/dev/dri/card0",
        "/dev/dri/renderD128",
        "/dev/kvm",
        "/dev/snd/pcmC0D0p",
        "/dev/input/event0",
        "/dev/bus/usb/001/001",
    ]

    for ddev in dangerous_devices:
        res = sanitizer.inspect_device(ddev)
        assert res.action == DeviceSanitizeAction.STRIP, f"Expected {ddev} to be STRIPPED"
        assert res.matched_rule == "STRIPPED_HOST_HARDWARE_DEVICE"


def test_sanitize_device_list_mixed_batch() -> None:
    sanitizer = ContainerDeviceSanitizer()

    candidates = [
        "/dev/null",
        "/dev/sda",
        "/dev/urandom",
        "/dev/nvme0n1",
        "/dev/tty",
        "/dev/mem",
    ]

    report = sanitizer.sanitize_device_list(candidates)
    assert report.total_inspected == 6
    assert report.is_fully_compliant is False
    assert set(report.allowed_devices) == {"/dev/null", "/dev/urandom", "/dev/tty"}
    assert set(report.stripped_devices) == {"/dev/sda", "/dev/nvme0n1", "/dev/mem"}
    assert len(report.reasons) == 3


def test_cgroup_and_docker_rules_generation() -> None:
    sanitizer = ContainerDeviceSanitizer()

    cgroup_rules = sanitizer.generate_cgroup_device_rules()
    assert len(cgroup_rules) >= 7

    # Ensure critical virtual devices are present
    assert "c 1:3 rwm" in cgroup_rules  # /dev/null
    assert "c 1:5 rwm" in cgroup_rules  # /dev/zero
    assert "c 1:9 rwm" in cgroup_rules  # /dev/urandom
    assert "c 5:0 rwm" in cgroup_rules  # /dev/tty
    assert "c 136:* rwm" in cgroup_rules  # pts

    # Ensure absolutely NO block device 'b' permissions are granted
    for rule in cgroup_rules:
        assert not rule.startswith("b "), f"Block device rule found in cgroup allowlist: {rule}"

    docker_args = sanitizer.generate_docker_device_args()
    assert len(docker_args) == len(cgroup_rules)
    assert any(arg == "--device-cgroup-rule=c 1:3 rwm" for arg in docker_args)


def test_facade_and_custom_configuration() -> None:
    facade = ContainerDeviceWhitelistFacade()

    # Initial check
    assert len(facade.get_standard_virtual_devices()) == len(STANDARD_VIRTUAL_DEVICES)
    assert len(facade.get_cgroup_device_rules()) >= 7

    # Custom allowed device added via config update
    new_cfg = ContainerDevicePolicyConfig(
        strict_minimal_allowlist=True,
        custom_allowed_devices=("/dev/custom_pseudo",),
    )
    facade.update_config(new_cfg)

    res_custom = facade.inspect_device("/dev/custom_pseudo")
    assert res_custom.action == DeviceSanitizeAction.ALLOW
    assert res_custom.matched_rule == "ALLOWED_VIRTUAL_DEVICE"

    # Block device should still be stripped
    res_sda = facade.inspect_device("/dev/sda")
    assert res_sda.action == DeviceSanitizeAction.STRIP
