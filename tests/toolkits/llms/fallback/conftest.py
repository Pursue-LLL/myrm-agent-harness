"""Fixtures for LLM fallback tests."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.fallback.probe_throttle import (
    get_global_probe_throttle,
)


@pytest.fixture(autouse=True)
def _reset_global_probe_throttle() -> None:
    """Reset GlobalProbeThrottle singleton before each test.

    GlobalProbeThrottle is a module-level singleton that persists across tests.
    Without this fixture, a probe recorded in one test can throttle probes in
    subsequent tests that reuse the same model name.
    """
    get_global_probe_throttle().clear()
