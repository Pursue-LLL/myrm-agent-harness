"""Real-LLM e2e tests for Dynamic Workflow orchestration script generation.

Exercises the reasoning-model-aware extraction in ``run_dynamic_workflow_stream``:
the orchestrator prompt is fed to a real LLM, the response is routed through
``extract_answer_text`` and ``strip_script_markdown``, and must yield a valid
Python orchestration script (not the literal ``"None"`` a reasoning model with
``content=None`` used to produce). No mocks on the LLM path.
"""

from __future__ import annotations

import ast

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.dynamic_workflow import ORCHESTRATOR_PROMPT
from myrm_agent_harness.agent.dynamic_workflow.preflight import (
    count_llm_query_calls,
    count_spawn_calls,
    strip_script_markdown,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text

pytestmark = pytest.mark.e2e


async def _generate_orchestration_script(llm, query: str) -> tuple[str, str]:
    """Feed ORCHESTRATOR_PROMPT to a real LLM and run the production extraction path."""
    messages = [
        SystemMessage(content=ORCHESTRATOR_PROMPT),
        HumanMessage(content=query),
    ]
    response = await llm.ainvoke(messages)
    raw_script = extract_answer_text(response)
    script_code = strip_script_markdown(raw_script)
    return raw_script, script_code


@pytest.mark.asyncio
async def test_orchestrator_generates_valid_python_script(basic_llm) -> None:
    """A real LLM produces a parseable Python orchestration script."""
    raw_script, script_code = await _generate_orchestration_script(
        basic_llm,
        "Orchestrate a workflow: spawn exactly one generalPurpose sub-agent "
        "to summarize the phrase HELLO_DW in one sentence, then print JSON results.",
    )

    assert isinstance(raw_script, str)
    assert raw_script.strip(), "extract_answer_text returned empty text for orchestrator"

    assert "<think>" not in raw_script, "think blocks must be stripped from the script"
    assert script_code.strip(), "strip_script_markdown produced an empty script"
    assert script_code != "None", (
        "orchestrator script must not be the literal 'None' a reasoning model with "
        "content=None used to produce"
    )

    tree = ast.parse(script_code)
    assert tree.body, "script must contain statements"
    assert count_spawn_calls(script_code) >= 0, "spawn counter must run on real output"


@pytest.mark.asyncio
async def test_orchestrator_script_references_ptc_tools(basic_llm) -> None:
    """The generated script exercises the PTC tool surface (spawn/llm_query/notify)."""
    _, script_code = await _generate_orchestration_script(
        basic_llm,
        "Split the following 3 items and summarize each with a lightweight LLM "
        "sub-call: ['alpha', 'beta', 'gamma']. Print the summaries.",
    )

    assert script_code.strip(), "script must be non-empty"
    single, batched = count_llm_query_calls(script_code)
    spawns = count_spawn_calls(script_code)
    assert (
        single + batched + spawns > 0
    ), "script should reference at least one PTC tool (spawn_subagent / llm_query)"
