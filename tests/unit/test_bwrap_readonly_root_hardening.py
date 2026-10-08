"""
[POS] tests/unit/test_bwrap_readonly_root_hardening.py
[INPUT] myrm_agent_harness.toolkits.code_execution.sandbox.providers.bwrap, myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types
[OUTPUT] Unit tests for BwrapProvider root readonly escape defense

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.sandbox.providers.bwrap import (
    BwrapProvider,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxPolicy,
)


def test_bwrap_wrap_command_enforces_remount_ro_root() -> None:
    """Verify that wrap_command explicitly includes --remount-ro / right after --dir / to prevent parent-rename escapes."""
    provider = BwrapProvider()
    policy = SandboxPolicy(
        writable_paths=("/tmp/workspace",),
        readable_paths=("/usr/local",),
        allow_network=False,
    )

    bin_name, args = provider.wrap_command(
        shell_path="/bin/sh",
        shell_args=("-c", "echo test"),
        work_dir="/tmp/workspace",
        policy=policy,
    )

    assert bin_name == "bwrap"
    assert "--dir" in args
    dir_idx = args.index("--dir")
    assert args[dir_idx + 1] == "/"

    # Critical security guardrail: --remount-ro / must follow --dir /
    assert "--remount-ro" in args
    remount_idx = args.index("--remount-ro")
    assert remount_idx == dir_idx + 2
    assert args[remount_idx + 1] == "/"

    # Verify unshare-net when network is prohibited
    assert "--unshare-net" in args
