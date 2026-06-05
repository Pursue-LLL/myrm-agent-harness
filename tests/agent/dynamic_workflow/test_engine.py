"""Unit tests for run_dynamic_workflow_stream engine."""

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.dynamic_workflow import run_dynamic_workflow_stream


class FakeLLM:
    def __init__(self, script: str = "print('hello')") -> None:
        self._script = script

    async def ainvoke(self, messages, config=None):
        return AIMessage(content=self._script)


@pytest.mark.asyncio
async def test_deterministic_workflow_id(tmp_path, monkeypatch):
    """workflow_id must be stable for the same chat_id + message_id pair."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    async def mock_ptc(context, executor, ptc_tools):
        class Result:
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    llm = FakeLLM()
    chunks1 = [
        c
        async for c in run_dynamic_workflow_stream(
            llm=llm,
            query="test",
            chat_history=[],
            chat_id="chat_a",
            message_id="msg_b",
        )
    ]
    chunks2 = [
        c
        async for c in run_dynamic_workflow_stream(
            llm=llm,
            query="test",
            chat_history=[],
            chat_id="chat_a",
            message_id="msg_b",
        )
    ]

    content1 = next(c["content"] for c in chunks1 if c.get("type") == "content")
    content2 = next(c["content"] for c in chunks2 if c.get("type") == "content")

    wf_id_1 = content1.split("`")[1]
    wf_id_2 = content2.split("`")[1]
    assert wf_id_1 == wf_id_2
    assert wf_id_1.startswith("wf_")


@pytest.mark.asyncio
async def test_workflow_status_steps(tmp_path, monkeypatch):
    """Engine yields init, planning, and execution status steps."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    async def mock_ptc(context, executor, ptc_tools):
        class Result:
            stdout = "done"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    llm = FakeLLM()
    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            llm=llm,
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
async def test_markdown_script_cleanup(tmp_path, monkeypatch):
    """LLM markdown fences must be stripped before PTC execution."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    captured_code: list[str] = []

    async def mock_ptc(context, executor, ptc_tools):
        captured_code.append(context.code)
        class Result:
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    llm = FakeLLM("```python\nprint('clean')\n```")
    _ = [
        c
        async for c in run_dynamic_workflow_stream(
            llm=llm,
            query="test",
            chat_history=[],
            chat_id="c1",
            message_id="m1",
        )
    ]

    assert captured_code
    assert captured_code[0] == "print('clean')"


@pytest.mark.asyncio
async def test_ptc_execution_failure(tmp_path, monkeypatch):
    """PTC failure must yield error status and error content."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    async def mock_ptc_fail(context, executor, ptc_tools):
        raise RuntimeError("sandbox exploded")

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc_fail,
    )

    llm = FakeLLM()
    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            llm=llm,
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
    assert "failed to execute" in content.lower()
    assert "sandbox exploded" in content
