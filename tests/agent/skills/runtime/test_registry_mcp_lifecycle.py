"""SkillRegistry MCP lifecycle tests."""

from __future__ import annotations

from myrm_agent_harness.agent.skills.runtime.registry import SkillRegistry
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata


def _mcp_skill(name: str) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"MCP skill {name}",
        mcp=MCPSkillData(server=name, tools=[], config=[]),
    )


def _storage_skill(name: str) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"Storage skill {name}",
        storage_skill_id=f"skill_{name}",
        storage_path=f"/skills/{name}",
    )


def test_clear_mcp_skills_removes_only_mcp_entries() -> None:
    registry = SkillRegistry()
    registry.register(_mcp_skill("github_mcp"))
    registry.register(_mcp_skill("notion_mcp"))
    registry.register(_storage_skill("user_skill"))

    registry.clear_mcp_skills()

    assert registry.get_skill("github_mcp") is None
    assert registry.get_skill("notion_mcp") is None
    assert registry.get_skill("user_skill") is not None


def test_clear_mcp_skills_is_noop_when_empty() -> None:
    registry = SkillRegistry()
    registry.register(_storage_skill("only_storage"))

    registry.clear_mcp_skills()

    assert registry.get_skill("only_storage") is not None


def test_metadata_summary_and_ipc_cache_coverage() -> None:
    from myrm_agent_harness.agent.skills.runtime.registry import get_metadata_summary
    from myrm_agent_harness.backends.skills.types import (
        SkillContract,
        SkillContractJudgment,
        SkillContractTrap,
        SkillContractVerification,
    )

    registry = SkillRegistry()
    assert get_metadata_summary([], hidden_skill_count=0) == "<skills>No skills available.</skills>"
    assert "skill_search_tool" in get_metadata_summary([], hidden_skill_count=3)

    contract = SkillContract(
        steps=("step1",),
        key_judgments=(
            SkillContractJudgment(
                judgment_id="j1",
                description="check status",
                condition="c",
                true_branch="t",
                false_branch="f",
            ),
        ),
        potential_traps=(SkillContractTrap(description="t" * 200, mitigation="m", severity="high"),),
        verification_steps=(
            SkillContractVerification(
                step_id="v1",
                description="v",
                validation_method="cmd",
                expected_output="ok",
            ),
        ),
        estimated_duration_seconds=10.0,
        dependencies=("jq",),
        success_criteria="all good",
    )
    mcp_s = _mcp_skill("srv_a")
    mcp_s.always = True
    mcp_s.contract = contract
    storage_s = _storage_skill("store_b")
    registry.register(mcp_s)
    registry.register(storage_s)
    assert len(registry.list_skills()) == 2
    assert len(registry.list_mcp_skills()) == 1
    assert len(registry.list_storage_skills()) == 1
    assert registry.get_mcp_skill_for_ipc("srv_a") is mcp_s

    xml_out = get_metadata_summary(registry.list_skills(), hidden_skill_count=2)
    assert "<contract" in xml_out
    assert "<dependencies>jq</dependencies>" in xml_out
    assert "<verify>v -&gt; ok</verify>" in xml_out
    assert "<trap" in xml_out

    registry.clear_mcp_skills()
    assert registry.get_skill("srv_a") is None
    assert registry.get_mcp_skill_for_ipc("srv_a") is mcp_s
    registry.clear()
    assert registry.get_mcp_skill_for_ipc("srv_a") is None


async def test_client_dict_helpers_and_connection_pool_edge_paths() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    import pytest

    from myrm_agent_harness.agent.security.workspace_trust.context import (
        get_workspace_root,
        get_workspace_trust_level,
    )
    from myrm_agent_harness.agent.security.workspace_trust.runtime import (
        apply_workspace_trust_for_root,
        clear_workspace_trust_runtime,
    )
    from myrm_agent_harness.agent.security.workspace_trust.types import WorkspaceTrustLevel
    from myrm_agent_harness.toolkits.mcp.client import MCPClientManager
    from myrm_agent_harness.toolkits.mcp.config import MCPConfig
    from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager
    from myrm_agent_harness.toolkits.mcp.connection_pool_types import ConnectionStatus

    conn_no_tls: dict[str, object] = {"url": "https://api.example.com/mcp"}
    assert MCPClientManager._build_ssl_context_from_dict("srv", conn_no_tls) is None
    assert MCPClientManager.build_tls_client_factory_from_dict("srv", conn_no_tls) is None

    conn_tls: dict[str, object] = {
        "url": "https://api.example.com/mcp",
        "ssl_verify": False,
    }
    ctx = MCPClientManager._build_ssl_context_from_dict("srv", conn_tls)
    assert ctx is not None
    factory = MCPClientManager.build_tls_client_factory_from_dict("srv", conn_tls)
    assert factory is not None
    http_client = MCPClientManager.build_streamable_http_client(
        headers={"X-Test": "1"},
        url="https://api.example.com/mcp",
        ssl_context=ctx,
    )
    await http_client.aclose()

    mgr = MCPConnectionManager(ttl=60, cleanup_interval=999)
    assert "connections=0" in repr(mgr)
    assert mgr.get_stats()["total_connections"] == 0
    assert mgr.refresh_server_auth("nonexistent", {"Authorization": "Bearer x"}) is False
    assert mgr._get_create_lock(None) is mgr._create_lock
    assert mgr._get_create_lock("hash_a") is mgr._get_create_lock("hash_a")
    assert mgr._get_spawn_semaphore() is mgr._get_spawn_semaphore()
    mgr._ensure_cleanup_running()

    fake_conn = MagicMock()
    fake_conn.status = ConnectionStatus.ACTIVE
    fake_conn.refresh_server_auth.return_value = True
    fake_conn._resolve_actor.return_value = None
    fake_conn.close = AsyncMock()
    mgr._connections["h_active"] = fake_conn
    assert mgr.refresh_server_auth("srv", {"Authorization": "Bearer y"}) is True

    cfg = MCPConfig(name="srv", type="stdio", command="echo", ssl_verify=False)
    with patch.object(mgr, "get_connection", AsyncMock(return_value=fake_conn)):
        resolver = mgr._make_actor_resolver([cfg], "srv")
        assert await resolver() is None

    with (
        patch.object(
            mgr,
            "_create_connection",
            AsyncMock(side_effect=RuntimeError("spawn boom")),
        ),
        pytest.raises(RuntimeError, match="spawn boom"),
    ):
        await mgr.get_connection([cfg])

    await mgr.close_all()

    level = apply_workspace_trust_for_root("/tmp/nonexistent-untrusted-ws")
    assert get_workspace_root() == "/tmp/nonexistent-untrusted-ws"
    assert get_workspace_trust_level() == level
    with (
        patch(
            "myrm_agent_harness.agent.security.workspace_trust.runtime.resolve_workspace_trust_level",
            return_value=WorkspaceTrustLevel.TRUSTED,
        ),
        patch(
            "myrm_agent_harness.agent.security.workspace_trust.runtime.load_repo_command_prefixes",
            return_value=("npx",),
        ),
    ):
        t_level = apply_workspace_trust_for_root("/tmp/trusted-ws")
        assert t_level == WorkspaceTrustLevel.TRUSTED
        assert get_workspace_root() == "/tmp/trusted-ws"
    clear_workspace_trust_runtime()
    assert get_workspace_root() is None
