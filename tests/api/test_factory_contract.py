"""Contract tests for ``create_skill_agent`` via the public API."""

from __future__ import annotations

import inspect

import pytest


@pytest.mark.api
def test_create_skill_agent_requires_runtime_spec() -> None:
    from myrm_agent_harness.api import create_skill_agent

    signature = inspect.signature(create_skill_agent)
    params = list(signature.parameters)
    assert params[0] == "spec"
    assert signature.parameters["spec"].default is inspect.Parameter.empty


@pytest.mark.api
def test_create_skill_agent_memory_extraction_defaults_true() -> None:
    from myrm_agent_harness.api import create_skill_agent

    param = inspect.signature(create_skill_agent).parameters["enable_memory_auto_extraction"]
    assert param.default is True


@pytest.mark.api
def test_api_create_skill_agent_matches_factory_impl() -> None:
    from myrm_agent_harness.agent.skill_agent_factory import create_skill_agent as factory_fn
    from myrm_agent_harness.api import create_skill_agent as api_fn

    assert api_fn is factory_fn
