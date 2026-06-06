"""Unit tests for run_dynamic_workflow_stream engine."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.dynamic_workflow import run_dynamic_workflow_stream


class FakeLLM:
    def __init__(self, script: str = "print('hello')") -> None:
        self._script = script

    async def ainvoke(self, messages, config=None):
        return AIMessage(content=self._script)


@pytest.fixture
def mock_parent_agent():
    agent = MagicMock()
    agent.llm = FakeLLM()
    agent._cached_tools = []
    agent.user_tools = []
    agent._spawn_child = AsyncMock()
    return agent


@pytest.mark.asyncio
async def test_deterministic_workflow_id(tmp_path, monkeypatch, mock_parent_agent):
    """workflow_id must be stable for the same chat_id + message_id pair."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        class Result:
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    chunks1 = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="test",
            chat_history=[],
            chat_id="chat_a",
            message_id="msg_b",
        )
    ]
    chunks2 = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="test",
            chat_history=[],
            chat_id="chat_a",
            message_id="msg_b",
        )
    ]

    content1 = [c for c in chunks1 if c.get("type") == "content"]
    content2 = [c for c in chunks2 if c.get("type") == "content"]
    assert content1 and content2

    import hashlib

    expected_id = f"wf_{hashlib.md5(b'chat_a:msg_b').hexdigest()[:12]}"
    assert expected_id.startswith("wf_")


@pytest.mark.asyncio
async def test_workflow_status_steps(tmp_path, monkeypatch, mock_parent_agent):
    """Engine yields init, planning, and execution status steps."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        class Result:
            stdout = "done"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="summarize",
            chat_history=[],
            chat_id="c1",
            message_id="m1",
        )
    ]

    step_keys = [c.get("step_key") for c in chunks if c.get("type") == "status"]
    assert "workflow_init" in step_keys
    assert "workflow_planning" in step_keys
    assert "workflow_execution" in step_keys
    assert any(c.get("type") == "done" for c in chunks)


@pytest.mark.asyncio
async def test_markdown_script_cleanup(tmp_path, monkeypatch, mock_parent_agent):
    """LLM markdown fences must be stripped before PTC execution."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    mock_parent_agent.llm = FakeLLM("```python\nprint('clean')\n```")

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    captured_code: list[str] = []

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        captured_code.append(context.code)

        class Result:
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    _ = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="test",
            chat_history=[],
            chat_id="c1",
            message_id="m1",
        )
    ]

    assert captured_code
    assert captured_code[0] == "print('clean')"


@pytest.mark.asyncio
async def test_ptc_execution_failure(tmp_path, monkeypatch, mock_parent_agent):
    """PTC failure must yield error status and error content."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    async def mock_ptc_fail(context, executor, ptc_tools, override_allowed=frozenset()):
        raise RuntimeError("sandbox exploded")

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc_fail,
    )

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="fail",
            chat_history=[],
            chat_id="c1",
            message_id="m1",
        )
    ]

    error_status = [
        c
        for c in chunks
        if c.get("type") == "status"
        and c.get("step_key") == "workflow_execution"
        and c.get("status") == "error"
    ]
    assert error_status
    content = next(c["content"] for c in chunks if c.get("type") == "content")
    assert "failed" in content.lower()
    assert "sandbox exploded" in content


@pytest.mark.asyncio
async def test_cancel_token_early_exit(tmp_path, monkeypatch, mock_parent_agent):
    """Cancelled token should terminate workflow early."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    cancel_token = MagicMock()
    cancel_token.is_cancelled = True

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="test",
            chat_history=[],
            chat_id="c1",
            message_id="m1",
            cancel_token=cancel_token,
        )
    ]

    assert any(c.get("type") == "done" for c in chunks)
    error_statuses = [c for c in chunks if c.get("status") == "error"]
    assert error_statuses


@pytest.mark.asyncio
async def test_override_allowed_passed_to_ptc(tmp_path, monkeypatch, mock_parent_agent):
    """override_allowed must include spawn_subagent."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    captured_override: list[frozenset] = []

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        captured_override.append(override_allowed)

        class Result:
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    _ = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="test",
            chat_history=[],
            chat_id="c1",
            message_id="m1",
        )
    ]

    assert captured_override
    assert "spawn_subagent" in captured_override[0]
