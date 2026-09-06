"""Real-LLM and full-link Pipeline Integration tests for Reasoning Preservation & Observation Compaction.

Tests end-to-end flow with real LLM configuration from .env.test:
1. Multi-turn dialogue with real model and reasoning anchors extraction.
2. Full ContextPipeline processing with ReasoningAnchorProcessor and ActiveToolResultPruneProcessor.
3. Verification that extracted anchors survive across pipeline stages and get cleanly injected into prompt context.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.engine import ContextPipeline, build_default_processors
from myrm_agent_harness.agent.context_management.strategies.reasoning.anchor_ledger import (
    clear_session_anchor_ledger,
    get_session_anchor_ledger,
)
from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM

pytestmark = pytest.mark.e2e

_ENV_TEST = Path(__file__).resolve().parents[4] / "myrm-agent" / "myrm-agent-server" / ".env.test"
_OPENAI_COMPAT = {"openai-like", "openai_compatible", "openai-compatible", "openai_like"}


def _normalize_model(raw: str) -> tuple[str, str | None]:
    if "/" in raw:
        prefix, model = raw.split("/", 1)
        if prefix in _OPENAI_COMPAT:
            return f"openai/{model}", "openai"
        return raw, None
    return raw, None


@pytest.fixture(autouse=True)
def _ensure_env_test() -> None:
    if _ENV_TEST.exists():
        for line in _ENV_TEST.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            if k and v:
                os.environ.setdefault(k, v)


def _get_real_llm() -> ChatLiteLLM:
    api_key = os.environ.get("BASIC_API_KEY", "") or os.environ.get("LITE_API_KEY", "")
    base_url = os.environ.get("BASIC_BASE_URL", "") or os.environ.get("LITE_BASE_URL", "")
    model = os.environ.get("BASIC_MODEL", "") or os.environ.get("LITE_MODEL", "")
    if not (api_key and base_url and model):
        pytest.skip("No LLM credentials found in .env.test")
    norm_model, provider = _normalize_model(model)
    return ChatLiteLLM(
        model=norm_model,
        api_key=api_key,
        api_base=base_url,
        custom_llm_provider=provider,
        temperature=0.0,
        max_tokens=1024,
    )


@pytest.mark.asyncio
async def test_reasoning_and_observation_compaction_real_llm_full_pipeline() -> None:
    """Full-link E2E: Real model call produces response; reasoning & observations are managed through ContextPipeline."""
    llm = _get_real_llm()
    session_id = "test_e2e_real_pipeline_session_001"
    clear_session_anchor_ledger(session_id)

    # 1. Execute a real LLM prompt to verify model health and generate authentic response
    user_prompt = "请用中文简短输出两句话：第一句必须包含'核心决策：采用异步架构'，第二句包含'约束：禁止阻塞主线程'。"
    response = await llm.ainvoke([HumanMessage(content=user_prompt)])
    assert response is not None
    assert response.content is not None
    resp_text = str(response.content)
    assert len(resp_text) > 0

    # 2. Construct authentic multi-turn history with tool messages and reasoning
    ai_turn_1 = AIMessage(
        content=resp_text,
        additional_kwargs={
            "reasoning_content": "分析需求：\n- 核心决策: 采用异步非阻塞架构保证高吞吐\n- 严格约束: 单次I/O等待严禁超过500ms\n因此确定该架构决策方案。"
        },
        tool_calls=[{"id": "call_inspect_db", "name": "bash_code_execute_tool", "args": {"cmd": "pg_isready"}}],
    )
    tool_msg_1 = ToolMessage(
        content="PostgreSQL server is ready accepting connections on port 5432.\n" + ("log details...\n" * 50),
        tool_call_id="call_inspect_db",
        name="bash_code_execute_tool",
    )
    human_turn_2 = HumanMessage(content="很好，请基于上述决策继续推进下一步。")

    messages = [
        HumanMessage(content=user_prompt),
        ai_turn_1,
        tool_msg_1,
        human_turn_2,
    ]

    # 3. Process through unified default ContextPipeline
    processors = build_default_processors(max_context_tokens=128000)
    pipeline = ContextPipeline(processors)

    context = ProcessorContext(
        messages=messages,
        user_query="推进下一步",
        chat_id=session_id,
        llm=llm,
        metadata={
            "model_name": getattr(llm, "model", "test-model"),
            "enable_active_tool_prune": True,
        },
    )

    result_context = await pipeline.process(context)

    # 4. Verify Reasoning Anchors in Ledger & Injected Context
    ledger = get_session_anchor_ledger(session_id)
    anchors = ledger.get_anchors()
    assert len(anchors) >= 1
    anchor_texts = [a.content for a in anchors]
    assert any("异步" in t or "严禁超过500ms" in t or "架构" in t for t in anchor_texts)

    # 5. Verify Prompt Cache friendly injection into last HumanMessage
    last_msg = result_context.messages[-1]
    assert isinstance(last_msg, HumanMessage)
    last_content = str(last_msg.content)
    assert "[PRESERVED REASONING ANCHORS & CONSTRAINTS]" in last_content

    # 6. Verify consumption awareness: tool_msg_1 is followed by human_turn_2, but not consumed by subsequent AI yet
    # Tool result remains intact or correctly handled without data loss
    assert any(isinstance(m, ToolMessage) and "PostgreSQL" in str(m.content) for m in result_context.messages)
