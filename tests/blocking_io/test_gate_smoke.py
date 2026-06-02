"""Smoke test: verify the blockbuster gate catches blocking IO and opt-out works.

Tests in this directory are automatically gated by the blockbuster
hookwrapper in conftest.py. The gate only fires for callers whose stack
includes ``myrm_agent_harness.*``.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from blockbuster import BlockingError


async def test_to_thread_is_not_blocked() -> None:
    """Offloading to a thread does not trigger blockbuster."""
    result = await asyncio.to_thread(os.path.exists, os.devnull)
    assert result is True


async def test_blockbuster_gate_catches_harness_blocking_io(tmp_path: Path) -> None:
    """Verify that the gate catches blocking IO from harness code.

    Calls a real harness utility that performs synchronous file write.
    """
    from myrm_agent_harness.infra.atomic_write import atomic_write

    target = tmp_path / "gate_test.txt"
    with pytest.raises(BlockingError):
        atomic_write(target, b"test")


@pytest.mark.allow_blocking_io
async def test_allow_blocking_io_marker_opts_out(tmp_path: Path) -> None:
    """Tests marked allow_blocking_io bypass the gate."""
    from myrm_agent_harness.infra.atomic_write import atomic_write

    target = tmp_path / "opt_out_test.txt"
    atomic_write(target, b"test")
    assert target.read_bytes() == b"test"
