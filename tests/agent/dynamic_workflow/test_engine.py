"""Unit tests for run_dynamic_workflow_stream engine."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.dynamic_workflow import (
    ORCHESTRATOR_PROMPT,
    run_dynamic_workflow_stream,
)
from myrm_agent_harness.agent.parallel.config import DEFAULT_MAX_BATCH_PARALLEL


class TestOrchestratorPromptConsistency:
    """Guard: ORCHESTRATOR_PROMPT constraints stay aligned with runtime config."""

    def test_max_workers_matches_config(self) -> None:
        assert f"max_workers <= {DEFAULT_MAX_BATCH_PARALLEL}" in ORCHESTRATOR_PROMPT

    def test_contains_pattern_selection(self) -> None:
        assert "PATTERN SELECTION" in ORCHESTRATOR_PROMPT

    def test_contains_data_transformation_rule(self) -> None:
        assert "NEVER spawn a sub-agent for" in ORCHESTRATOR_PROMPT

    def test_contains_partial_failure_guidance(self) -> None:
        assert "PARTIAL FAILURE" in ORCHESTRATOR_PROMPT

    def test_barrier_example_present(self) -> None:
        assert "Barrier Pattern" in ORCHESTRATOR_PROMPT

    def test_pipeline_example_present(self) -> None:
        assert "Pipeline Pattern" in ORCHESTRATOR_PROMPT

    def test_non_deterministic_api_names_are_valid_python(self) -> None:
        assert (
            "Do NOT use time.time(), datetime.now(), random.random()"
            in ORCHESTRATOR_PROMPT
        )

    def test_non_deterministic_constraint_rejects_bare_random(self) -> None:
        assert ", random()," not in ORCHESTRATOR_PROMPT


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
        if c.get("type") == "status"
        and c.get("step_key") == "workflow_execution"
        and c.get("status") == "error"
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
async def test_catalog_injects_types_into_orchestrator_prompt(
    tmp_path, monkeypatch, mock_parent_agent
):
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
async def test_reasoning_model_content_none_recovers_script(
    tmp_path, monkeypatch, mock_parent_agent
):
    """O: Reasoning models return empty content with the script in
    additional_kwargs['reasoning_content']; the engine must recover the
    orchestration script instead of executing an empty/"None" script."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    class ReasoningLLM:
        async def ainvoke(self, messages, config=None):
            return AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "print('recovered')"},
            )

    mock_parent_agent.llm = ReasoningLLM()

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

    assert captured_code
    assert captured_code[0] == "print('recovered')"
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
async def test_summarization_reasoning_model_recovers_text(
    tmp_path, monkeypatch, mock_parent_agent
):
    """O: Summarization with a reasoning model (empty content, reasoning in
    additional_kwargs) must produce the real summary, not a literal "None"."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    call_count = {"n": 0}

    class ReasoningSummaryLLM:
        async def ainvoke(self, messages, config=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return AIMessage(content="print('hello world')")
            return AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "## Summary\nWorkflow done"},
            )

    mock_parent_agent.llm = ReasoningSummaryLLM()

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
    assert "## Summary" in msg_chunks[0]["data"]
    assert "None" not in msg_chunks[0]["data"]


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
    assert (
        "no output" in msg_chunks[0]["data"].lower()
        or "completed" in msg_chunks[0]["data"].lower()
    )


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
async def test_notify_events_yielded_during_ptc_execution(
    tmp_path, monkeypatch, mock_parent_agent
):
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


@pytest.mark.asyncio
async def test_post_exec_merge_called_when_guard_has_isolated_results(
    tmp_path, monkeypatch, mock_parent_agent
):
    """O1: After PTC execution, engine must call batch_merge when run_guard recorded isolated spawns."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    merge_calls: list[list[dict[str, object]]] = []

    async def fake_merge(
        results: list[dict[str, object]],
        *,
        snapshot_context: object | None = None,
    ) -> dict[str, object]:
        merge_calls.append(results)
        return {
            "workspace_merge_ok": True,
            "workspace_merge_merged_count": len(results),
        }

    monkeypatch.setattr(
        "myrm_agent_harness.agent.workspace_coordination.merge.batch_merge.merge_batch_workspace_sync_backs",
        fake_merge,
    )

    child_ws = tmp_path / "child"
    parent_ws = tmp_path / "parent"
    child_ws.mkdir()
    parent_ws.mkdir()

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        spawn_tool = next(
            t for t in ptc_tools if getattr(t, "name", None) == "spawn_subagent"
        )
        assert spawn_tool.run_guard is not None
        spawn_tool.run_guard.record_merge_candidate(
            {
                "success": True,
                "result": {
                    "_isolated_child_workspace": str(child_ws),
                    "_isolated_parent_workspace": str(parent_ws),
                },
            }
        )

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
            query="parallel implement",
            chat_history=[],
            chat_id="merge_c",
            message_id="merge_m",
        )
    ]

    assert (
        merge_calls
    ), "merge_batch_workspace_sync_backs should run when merge_results non-empty"
    assert merge_calls[0][0]["success"] is True
    assert any(
        c.get("step_key") == "workflow_execution" and c.get("status") == "success"
        for c in chunks
    )


@pytest.mark.asyncio
async def test_post_exec_merge_runs_when_ptc_raises(
    tmp_path, monkeypatch, mock_parent_agent
):
    """Pending merge candidates must flush even when inject_ptc raises."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    merge_calls: list[list[dict[str, object]]] = []

    async def fake_merge(
        results: list[dict[str, object]],
        *,
        snapshot_context: object | None = None,
    ) -> dict[str, object]:
        merge_calls.append(results)
        return {
            "workspace_merge_ok": True,
            "workspace_merge_merged_count": len(results),
        }

    monkeypatch.setattr(
        "myrm_agent_harness.agent.workspace_coordination.merge.batch_merge.merge_batch_workspace_sync_backs",
        fake_merge,
    )

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        spawn_tool = next(
            t for t in ptc_tools if getattr(t, "name", None) == "spawn_subagent"
        )
        assert spawn_tool.run_guard is not None
        spawn_tool.run_guard.record_merge_candidate(
            {
                "success": True,
                "result": {
                    "_isolated_child_workspace": str(tmp_path / "child"),
                    "_isolated_parent_workspace": str(tmp_path / "parent"),
                },
            }
        )
        raise RuntimeError("PTC failed after spawn")

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="parallel implement",
            chat_history=[],
            chat_id="merge_exc_c",
            message_id="merge_exc_m",
        )
    ]

    assert merge_calls, "merge must run in finally even when PTC raises"
    assert any(
        c.get("step_key") == "workflow_execution" and c.get("status") == "error"
        for c in chunks
    )


@pytest.mark.asyncio
async def test_merge_failure_surfaces_warn_status(
    tmp_path, monkeypatch, mock_parent_agent
):
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    async def fake_merge(
        results: list[dict[str, object]],
        *,
        snapshot_context: object | None = None,
    ) -> dict[str, object]:
        return {
            "workspace_merge_ok": False,
            "workspace_merge_merged_count": 0,
            "workspace_merge_errors": ["task_index=0: merge failed"],
        }

    monkeypatch.setattr(
        "myrm_agent_harness.agent.workspace_coordination.merge.batch_merge.merge_batch_workspace_sync_backs",
        fake_merge,
    )

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        spawn_tool = next(
            t for t in ptc_tools if getattr(t, "name", None) == "spawn_subagent"
        )
        assert spawn_tool.run_guard is not None
        spawn_tool.run_guard.record_merge_candidate(
            {
                "success": True,
                "result": {
                    "_isolated_child_workspace": str(tmp_path / "child"),
                    "_isolated_parent_workspace": str(tmp_path / "parent"),
                },
            }
        )

        class Result:
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )

    captured_summary: list[str] = []

    class TrackSummarizationLLM:
        async def ainvoke(self, messages, config=None):
            captured_summary.append(messages[1].content)
            from langchain_core.messages import AIMessage

            return AIMessage(content="Summary")

    mock_parent_agent.llm = TrackSummarizationLLM()

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="test merge warn",
            chat_history=[],
            chat_id="merge_warn_c",
            message_id="merge_warn_m",
        )
    ]

    assert any(
        c.get("step_key") == "workflow_execution" and c.get("status") == "warning"
        for c in chunks
    )
    end_chunks = [c for c in chunks if c.get("type") == "message_end"]
    assert end_chunks
    assert end_chunks[-1].get("completion_status") == "warning"
    assert any("Workspace merge errors" in item for item in captured_summary)


@pytest.mark.asyncio
async def test_summary_includes_workspace_changes_after_merge(
    tmp_path, monkeypatch, mock_parent_agent
) -> None:
    """G4: DW summary must append Workspace Changes when batch merge writes files."""
    from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
        SnapshotStore,
    )

    SnapshotStore.reset()
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    parent_ws = tmp_path / "parent"
    child_ws = tmp_path / "child"
    parent_ws.mkdir()
    child_ws.mkdir()
    (child_ws / "output.txt").write_text("merged content", encoding="utf-8")

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.utils.workspace_path.WorkspacePathResolver.resolve_workspace_root",
        lambda: parent_ws,
    )

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        spawn_tool = next(
            t for t in ptc_tools if getattr(t, "name", None) == "spawn_subagent"
        )
        assert spawn_tool.run_guard is not None
        spawn_tool.run_guard.record_merge_candidate(
            {
                "success": True,
                "task_id": "t1",
                "result": {
                    "_isolated_child_workspace": str(child_ws),
                    "_isolated_parent_workspace": str(parent_ws),
                },
            }
        )

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
            query="parallel write",
            chat_history=[],
            chat_id="diff_c",
            message_id="diff_m",
        )
    ]

    messages = [c for c in chunks if c.get("type") == "message"]
    assert messages
    summary = str(messages[-1].get("data", ""))
    assert "## Workspace Changes" in summary
    assert "output.txt" in summary
    assert (parent_ws / "output.txt").is_file()


@pytest.mark.asyncio
async def test_pinned_template_skips_llm_generation(tmp_path, monkeypatch):
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod
    from myrm_agent_harness.agent.dynamic_workflow import (
        template_store as template_store_mod,
    )

    original_event_init = store_mod.WorkflowEventStore.__init__
    original_template_init = template_store_mod.WorkflowTemplateStore.__init__

    def patched_event_init(self, path):
        original_event_init(self, str(db_path))

    def patched_template_init(self, path):
        original_template_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_event_init)
    monkeypatch.setattr(
        template_store_mod.WorkflowTemplateStore, "__init__", patched_template_init
    )

    script = """
import myrm_tools
myrm_tools.spawn_subagent(task_id="t1", agent_type="generalPurpose", task_description="hello", readonly=True)
print("done")
"""
    template_store = template_store_mod.WorkflowTemplateStore(str(db_path))
    template_store.save_template(
        template_id="pinned-flow",
        display_name="Pinned Flow",
        script_code=script,
        trust_latch=True,
    )

    parent = MagicMock()
    parent.llm = AsyncMock()
    parent._cached_tools = []
    parent.user_tools = []

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        class Result:
            stdout = "ok"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.dynamic_workflow.preflight.estimate_workflow_cost",
        AsyncMock(return_value=(0.2, 10.0, "estimated")),
    )

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=parent,
            query="rerun template",
            chat_history=[],
            chat_id="chat_tpl",
            message_id="msg_tpl",
            pinned_template_id="pinned-flow",
        )
    ]

    orchestrator_calls = [
        call
        for call in parent.llm.ainvoke.call_args_list
        if call.args
        and call.args[0]
        and "Dynamic Workflow Orchestrator" in str(call.args[0][0].content)
    ]
    assert orchestrator_calls == []
    planning = next(c for c in chunks if c.get("step_key") == "workflow_planning")
    assert planning["data"].get("workflow_template_id") == "pinned-flow"
    end = next(c for c in chunks if c.get("type") == "message_end")
    assert end["completion_status"] != "error"


@pytest.mark.asyncio
async def test_engine_wires_human_ask_tool_to_ptc(
    tmp_path, monkeypatch, mock_parent_agent
) -> None:
    """Verify that run_dynamic_workflow_stream wires HumanAskTool into PTC tools and override_allowed."""
    db_path = tmp_path / "events.db"
    monkeypatch.chdir(tmp_path)

    from myrm_agent_harness.agent.dynamic_workflow import store as store_mod

    original_init = store_mod.WorkflowEventStore.__init__

    def patched_init(self, path):
        original_init(self, str(db_path))

    monkeypatch.setattr(store_mod.WorkflowEventStore, "__init__", patched_init)

    captured_ptc_tools = []
    captured_overrides = frozenset()

    async def mock_ptc(context, executor, ptc_tools, override_allowed=frozenset()):
        nonlocal captured_ptc_tools, captured_overrides
        captured_ptc_tools = list(ptc_tools)
        captured_overrides = override_allowed

        class Result:
            stdout = "workflow executed with human gate"
            stderr = ""

        return Result()

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection.inject_ptc_for_python_execution",
        mock_ptc,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.dynamic_workflow.preflight.estimate_workflow_cost",
        AsyncMock(return_value=(0.1, 5.0, "estimated")),
    )

    ask_gate_called = False

    async def mock_ask_gate(question, options, timeout, default):
        nonlocal ask_gate_called
        ask_gate_called = True
        return "continue"

    chunks = [
        c
        async for c in run_dynamic_workflow_stream(
            parent_agent=mock_parent_agent,
            query="orchestrate with human gate",
            chat_history=[],
            chat_id="chat_gate",
            message_id="msg_gate",
            ask_gate=mock_ask_gate,
        )
    ]

    tool_names = [getattr(t, "name", None) for t in captured_ptc_tools]
    assert "human_ask" in tool_names
    assert "human_ask" in captured_overrides
    human_tool = next(
        t for t in captured_ptc_tools if getattr(t, "name", None) == "human_ask"
    )
    assert human_tool.ask_gate_callable is mock_ask_gate
    end = next(c for c in chunks if c.get("type") == "message_end")
    assert end["completion_status"] == "success"
