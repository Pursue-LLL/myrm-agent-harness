from myrm_agent_harness.agent.types import AgentRuntimeSpec, WorkspaceBinding


def test_agent_runtime_spec_initialization():
    spec = AgentRuntimeSpec(
        name="Test Agent",
        system_prompt="Test prompt",
        mcp_servers=[],
        agent_id="test_agent",
        workspace_binding=WorkspaceBinding(root_path="/tmp/test", mode="chat"),
    )

    assert spec.system_prompt == "Test prompt"
    assert spec.agent_id == "test_agent"
    assert spec.workspace_binding.root_path == "/tmp/test"
    assert spec.workspace_binding.mode == "chat"


def test_workspace_binding_modes():
    binding = WorkspaceBinding(root_path="/tmp/test", mode="background")
    assert binding.mode == "background"

    binding2 = WorkspaceBinding(root_path="/tmp/test", mode="subagent")
    assert binding2.mode == "subagent"
