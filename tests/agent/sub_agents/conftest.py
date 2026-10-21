"""Shared fixtures for sub-agent tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.execution_evidence import (
    ExecutionEvidence,
    record_execution,
    track_execution,
)


@pytest.fixture
def verifier_ran_code() -> Iterator[None]:
    """Report that every verifier round launched a command.

    Verifier rounds in tests run against a fake ``spawn_child`` that never reaches an executor, so the
    execution evidence behind the PASS gate would stay empty. Tests that need real evidence record it
    themselves with ``record_execution()`` instead of using this fixture.
    """

    @contextmanager
    def _executed() -> Iterator[ExecutionEvidence]:
        with track_execution() as evidence:
            record_execution()
            yield evidence

    with patch("myrm_agent_harness.agent.sub_agents._verifier_round.track_execution", _executed):
        yield
