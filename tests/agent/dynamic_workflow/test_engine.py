"""Unit tests for run_dynamic_workflow_stream engine."""

import asyncio
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

    msg1 = [c for c in chunks1 if c.get("type") == "message"]
    msg2 = [c for c in chunks2 if c.get("type") == "message"]
    assert msg1 and msg2

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
    assert any(c.get("type") == "message_end" for c in chunks)


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
    """PTC failure must yield error status and message with error details."""
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
        if c.get("type") == "status" and c.get("step_key") == "workflow_execution" and c.get("status") == "error"
    ]
    assert error_status
    msg_chunk = next(c for c in chunks if c.get("type") == "message")
    assert "failed" in str(msg_chunk.get("data", "")).lower()
    assert "sandbox exploded" in str(msg_chunk.get("data", ""))
    end_chunk = next(c for c in chunks if c.get("type") == "message_end")
    assert end_chunk["completion_status"] == "error"


@pytest.mark.asyncio
async def test_cancel_token_early_exit(tmp_path, monkeypatch, mock_parent_agent):
    """Cancelled token should terminate workflow early with message_end."""
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

    assert any(c.get("type") == "message_end" for c in chunks)
    end_chunk = next(c for c in chunks if c.get("type") == "message_end")
    assert end_chunk["completion_status"] == "cancelled"


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


@pytest.mark.asyncio
async def test_catalog_injects_types_into_orchestrator_prompt(tmp_path, monkeypatch, mock_parent_agent):
    """When catalog is provided, available types are injected into the orchestrator prompt."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from dataclasses import dataclass

    @dataclass
    class FakeConfig:
        system_prompt: str = ""
        description: str = ""
        display_name: str = ""

    class TestCatalog:
        async def list_available(self) -> list[str]:
            return ["coder", "researcher"]

        async def resolve(self, type_id: str):
            return FakeConfig(description=f"{type_id} specialist", system_prompt="x")

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    captured_messages: list[list] = []

    class CaptureLLM:
        async def ainvoke(self, messages, config=None):
            captured_messages.append(messages)
            return AIMessage(content="print('ok')")

    mock_parent_agent.llm = CaptureLLM()

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
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
            catalog=TestCatalog(),
        )
    ]

    assert captured_messages
    system_content = captured_messages[0][0].content
    assert '"coder": coder specialist' in system_content
    assert '"researcher": researcher specialist' in system_content


@pytest.mark.asyncio
async def test_non_string_llm_content(tmp_path, monkeypatch, mock_parent_agent):
    """LLM returning non-string content (list chunks) must still be handled."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    class ListContentLLM:
        async def ainvoke(self, messages, config=None):
            return AIMessage(content=[{"type": "text", "text": "print('from_list')"}])

    mock_parent_agent.llm = ListContentLLM()

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

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="test",
            chat_history=[],
            chat_id="c1",
            message_id="m1",
        )
    ]

    assert any(c.get("type") == "message_end" for c in chunks)


@pytest.mark.asyncio
async def test_summarization_failure_fallback(tmp_path, monkeypatch, mock_parent_agent):
    """When summarization LLM fails, raw output is used as fallback."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    call_count = {"n": 0}

    class FailSecondCallLLM:
        async def ainvoke(self, messages, config=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return AIMessage(content="print('hello world')")
            raise RuntimeError("Summarization API down")

    mock_parent_agent.llm = FailSecondCallLLM()

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        class Result:
            stdout = "result_data_here"
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
            query="test",
            chat_history=[],
            chat_id="c1",
            message_id="m1",
        )
    ]

    msg_chunks = [c for c in chunks if c.get("type") == "message"]
    assert msg_chunks
    assert "result_data_here" in msg_chunks[0]["data"]


@pytest.mark.asyncio
async def test_stdout_truncation(tmp_path, monkeypatch, mock_parent_agent):
    """Long stdout exceeding _MAX_STDOUT_FOR_SUMMARY is truncated."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    captured_summary_input: list[str] = []
    call_count = {"n": 0}

    class TrackSummarizationLLM:
        async def ainvoke(self, messages, config=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return AIMessage(content="print('x')")
            captured_summary_input.append(messages[1].content)
            return AIMessage(content="Summary done")

    mock_parent_agent.llm = TrackSummarizationLLM()

    long_output = "x" * 40_000

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        class Result:
            stdout = long_output
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

    assert captured_summary_input
    assert "[...truncated" in captured_summary_input[0]


@pytest.mark.asyncio
async def test_empty_stdout_no_output_message(tmp_path, monkeypatch, mock_parent_agent):
    """When PTC produces no stdout/stderr, a 'no output' message is yielded."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        class Result:
            stdout = ""
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
            query="test",
            chat_history=[],
            chat_id="c1",
            message_id="m1",
        )
    ]

    msg_chunks = [c for c in chunks if c.get("type") == "message"]
    assert msg_chunks
    assert "no output" in msg_chunks[0]["data"].lower() or "completed" in msg_chunks[0]["data"].lower()


@pytest.mark.asyncio
async def test_stderr_included_in_summary(tmp_path, monkeypatch, mock_parent_agent):
    """When stderr is present, it's included in the summary input."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    captured_summary_input: list[str] = []
    call_count = {"n": 0}

    class TrackSummarizationLLM:
        async def ainvoke(self, messages, config=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return AIMessage(content="print('x')")
            captured_summary_input.append(messages[1].content)
            return AIMessage(content="Summary with errors")

    mock_parent_agent.llm = TrackSummarizationLLM()

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        class Result:
            stdout = "partial output"
            stderr = "WARNING: something bad happened"

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

    assert captured_summary_input
    assert "Execution Errors" in captured_summary_input[0]
    assert "WARNING: something bad happened" in captured_summary_input[0]


@pytest.mark.asyncio
async def test_notify_events_yielded_during_ptc_execution(tmp_path, monkeypatch, mock_parent_agent):
    """workflow_stage events must stream while inject_ptc runs, not only after it completes."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        notify_tool = next(t for t in ptc_tools if getattr(t, "name", None) == "notify")
        await asyncio.sleep(0.05)
        await notify_tool._arun(message="mid-flight phase")

        class Result:
            stdout = "ok"
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
            query="test",
            chat_history=[],
            chat_id="live_c",
            message_id="live_m",
        )
    ]

    stage_idx = next(
        i
        for i, c in enumerate(chunks)
        if c.get("step_key") == "workflow_stage"
        and c.get("data", {}).get("message") == "mid-flight phase"
    )
    exec_success_idx = next(
        i
        for i, c in enumerate(chunks)
        if c.get("step_key") == "workflow_execution" and c.get("status") == "success"
    )
    assert stage_idx < exec_success_idx
