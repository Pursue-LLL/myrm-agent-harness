"""Smoke tests for ``myrm_agent_harness.api`` — the external integration surface."""

from __future__ import annotations

import importlib
import inspect
import sys
from typing import Protocol

import pytest


@pytest.mark.api
def test_api_package_exports_match_all() -> None:
    api = importlib.import_module("myrm_agent_harness.api")
    assert sorted(api.__all__) == sorted(
        [
            "AgentConfig",
            "AgentEventType",
            "AgentProfileBackend",
            "AgentRuntimeConfig",
            "AgentRuntimeSpec",
            "AgentStreamEvent",
            "CompletionStatus",
            "ConfigIncompleteError",
            "HookEvent",
            "HookRegistryProtocol",
            "IntegrationProvider",
            "KanbanStore",
            "LLMConfig",
            "SkillAgent",
            "SkillBackend",
            "create_skill_agent",
            "get_distribution_mode",
            "is_compiled_distribution",
        ]
    )


@pytest.mark.api
def test_api_lazy_exports_resolve_and_cache() -> None:
    import myrm_agent_harness.api as api

    for name in api.__all__:
        api.__dict__.pop(name, None)

    for name in api.__all__:
        value = getattr(api, name)
        assert value is not None
        assert api.__dict__[name] is value


@pytest.mark.api
def test_api_config_submodule_exports() -> None:
    from myrm_agent_harness.api.config import (
        AgentConfig,
        ConfigIncompleteError,
        LLMConfig,
        StorageConfig,
        ToolGatewayConfig,
    )

    assert inspect.isclass(AgentConfig)
    assert inspect.isclass(LLMConfig)
    assert inspect.isclass(StorageConfig)
    assert inspect.isclass(ToolGatewayConfig)
    assert issubclass(ConfigIncompleteError, Exception)


@pytest.mark.api
def test_api_types_submodule_exports_without_factory() -> None:
    before = set(sys.modules)
    types_mod = importlib.import_module("myrm_agent_harness.api.types")
    loaded = set(sys.modules) - before

    assert "myrm_agent_harness.agent.skill_agent_factory" not in loaded
    assert hasattr(types_mod, "AgentRuntimeConfig")
    assert hasattr(types_mod, "AgentStreamEvent")
    assert hasattr(types_mod, "CompletionStatus")


@pytest.mark.api
def test_api_protocols_are_extension_contracts() -> None:
    from myrm_agent_harness.api.protocols import (
        AgentProfileBackend,
        HookRegistryProtocol,
        IntegrationProvider,
        KanbanStore,
        SkillBackend,
    )

    protocol_types = (
        AgentProfileBackend,
        HookRegistryProtocol,
        IntegrationProvider,
        KanbanStore,
        SkillBackend,
    )
    for protocol_type in protocol_types:
        assert inspect.isclass(protocol_type)
        assert issubclass(protocol_type, Protocol) or getattr(protocol_type, "_is_protocol", False)


@pytest.mark.api
def test_create_skill_agent_is_async_factory() -> None:
    from myrm_agent_harness.api import create_skill_agent

    assert callable(create_skill_agent)
    assert inspect.iscoroutinefunction(create_skill_agent)


@pytest.mark.api
def test_distribution_helpers_report_source_mode_in_dev() -> None:
    from myrm_agent_harness._distribution import DistributionMode
    from myrm_agent_harness.api import get_distribution_mode, is_compiled_distribution

    assert get_distribution_mode() is DistributionMode.SOURCE
    assert is_compiled_distribution() is False
