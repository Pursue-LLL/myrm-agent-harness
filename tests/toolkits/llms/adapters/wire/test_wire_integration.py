"""Integration tests for Responses wire invocation (requires network + OpenCode key)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _opencode_key() -> str | None:
    path = Path.home() / ".cursor-byok/opencode-go.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    accounts = data.get("account_keys")
    if isinstance(accounts, dict) and accounts.get("account-1"):
        return str(accounts["account-1"])
    return None


@pytest.mark.asyncio
async def test_chatlitellm_responses_stream() -> None:
    key = _opencode_key()
    if not key:
        pytest.skip("OpenCode Go key not configured")

    from langchain_core.messages import HumanMessage

    from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model

    llm = create_litellm_model(
        model="openai/muse-spark-1.2-contributor",
        api_key=key,
        base_url="https://opencode.ai/zen/go/v1",
        wire_protocol="responses",
        streaming=True,
        model_kwargs={"extra_body": {"reasoning": {"effort": "low"}}},
    )
    chunks: list[str] = []
    async for chunk in llm.astream([HumanMessage(content="Reply exactly: STREAM_WIRE_OK")]):
        if chunk.content:
            chunks.append(str(chunk.content))
    text = "".join(chunks)
    assert "STREAM_WIRE_OK" in text
