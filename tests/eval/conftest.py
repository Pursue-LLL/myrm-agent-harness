"""Shared fixtures for the eval test suite."""

import sys

import pytest

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local import LocalExecutor


@pytest.fixture
def executor(tmp_path, monkeypatch):
    from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import (
        NullProvider,
    )
    from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
        SandboxStatus,
    )

    _null_result = (
        NullProvider(),
        SandboxStatus(enabled=False, provider_name="null", reason="test"),
    )

    def _fake(**_kwargs):
        return _null_result

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider",
        _fake,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector.detect_sandbox_provider",
        _fake,
    )
    # test_suite assertions run `python -m pytest` inside the sandbox bash session;
    # point the shared venv at the interpreter running the tests so pytest resolves.
    config = ExecutionConfig()
    config.local.shared_venv_path = sys.prefix
    ex = LocalExecutor(config)
    ex.bind_workspace(str(tmp_path))
    return ex

