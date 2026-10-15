"""resolve_verifier: read-only verifier choice and refusal of a verifier that could never produce a counted PASS."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import BaseTool, StructuredTool

from myrm_agent_harness.agent.sub_agents.types import (
    ControlScope,
    DelegateRole,
    MemoryIsolationPolicy,
    SubagentConfig,
    WorkspacePolicy,
)
from myrm_agent_harness.agent.sub_agents.verifier_selection import VerifierUnavailableError, resolve_verifier

_BASH = "bash_code_execute_tool"


def _noop() -> str:
    return ""


def _tools(*names: str) -> list[BaseTool]:
    return [StructuredTool.from_function(func=_noop, name=name, description=name) for name in names]


def _catalog(**configs: SubagentConfig) -> AsyncMock:
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(side_effect=configs.get)
    return catalog


@pytest.mark.asyncio
async def test_resolved_verifier_is_returned_read_only() -> None:
    reviewer = SubagentConfig(system_prompt="review", tools=(_BASH, "file_read_tool"))
    worker = SubagentConfig(system_prompt="work")

    verifier_type, config = await resolve_verifier(
        _catalog(reviewer=reviewer), "reviewer", "coding", worker, _tools(_BASH, "file_read_tool")
    )

    assert verifier_type == "reviewer"
    assert config.system_prompt == "review"
    assert config.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX
    assert reviewer.workspace_policy != WorkspacePolicy.READ_ONLY_SANDBOX


@pytest.mark.asyncio
async def test_verifier_defaults_to_the_worker_type() -> None:
    coding = SubagentConfig(system_prompt="code")

    verifier_type, config = await resolve_verifier(
        _catalog(coding=coding), None, "coding", SubagentConfig(system_prompt="work"), _tools(_BASH)
    )

    assert verifier_type == "coding"
    assert config.system_prompt == "code"


@pytest.mark.parametrize("catalog", [None, _catalog()], ids=["no-catalog", "unknown-type"])
@pytest.mark.asyncio
async def test_unresolved_verifier_falls_back_to_the_worker(catalog: AsyncMock | None) -> None:
    worker = SubagentConfig(system_prompt="work")

    verifier_type, config = await resolve_verifier(catalog, "ghost", "coding", worker, _tools(_BASH))

    assert verifier_type == "coding"
    assert config.system_prompt == "work"
    assert config.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX


@pytest.mark.asyncio
async def test_fallback_verifier_keeps_the_workers_memory_write_block() -> None:
    worker = SubagentConfig(system_prompt="work", memory_isolation=MemoryIsolationPolicy.READ_ONLY_GLOBAL)

    _, config = await resolve_verifier(None, None, "coding", worker, _tools(_BASH))

    assert {"memory_save_tool", "memory_manage_tool"} <= config.disallowed_tools


@pytest.mark.parametrize("from_catalog", [True, False], ids=["catalog-resolved", "worker-fallback"])
@pytest.mark.asyncio
async def test_verifier_never_orchestrates_or_delegates(from_catalog: bool) -> None:
    orchestrator = SubagentConfig(
        system_prompt="orchestrate",
        control_scope=ControlScope.ORCHESTRATOR,
        max_spawn_depth=1,
        delegation_role=DelegateRole.ORCHESTRATOR,
        delegation_catalog=_catalog(),
        delegation_allowed_types=frozenset({"coding"}),
    )
    catalog = _catalog(reviewer=orchestrator) if from_catalog else None

    _, config = await resolve_verifier(catalog, "reviewer", "reviewer", orchestrator, _tools(_BASH))

    assert config.control_scope == ControlScope.LEAF
    assert config.max_spawn_depth == 0
    assert config.delegation_role == DelegateRole.LEAF
    assert config.delegation_catalog is None
    assert config.delegation_allowed_types is None
    assert orchestrator.control_scope == ControlScope.ORCHESTRATOR


@pytest.mark.asyncio
async def test_catalog_resolved_verifier_keeps_its_memory_write_block() -> None:
    reviewer = SubagentConfig(system_prompt="review", memory_isolation=MemoryIsolationPolicy.READ_ONLY_GLOBAL)

    _, config = await resolve_verifier(
        _catalog(reviewer=reviewer), "reviewer", "coding", SubagentConfig(system_prompt="work"), _tools(_BASH)
    )

    assert {"memory_save_tool", "memory_manage_tool"} <= config.disallowed_tools


@pytest.mark.parametrize(
    ("config", "parent_tools"),
    [
        (SubagentConfig(system_prompt="v", tools=("web_search_tool",)), (_BASH, "web_search_tool")),
        (SubagentConfig(system_prompt="v", disallowed_tools=frozenset({_BASH})), (_BASH, "file_read_tool")),
        (SubagentConfig(system_prompt="v"), ("file_read_tool",)),
    ],
    ids=["allowlist-without-bash", "bash-disallowed", "parent-without-bash"],
)
@pytest.mark.asyncio
async def test_verifier_that_cannot_run_commands_is_refused(
    config: SubagentConfig, parent_tools: tuple[str, ...]
) -> None:
    with pytest.raises(VerifierUnavailableError, match="'reviewer' cannot run commands"):
        await resolve_verifier(
            _catalog(reviewer=config), "reviewer", "coding", SubagentConfig(system_prompt="work"), _tools(*parent_tools)
        )
