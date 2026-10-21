"""Web fetch meta-tool blocked-hostname decontamination tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.errors import ToolErrorCategory
from myrm_agent_harness.toolkits.web_fetch.web_fetch_agent_tools import (
    create_web_fetch_tool,
)
from myrm_agent_harness.utils.errors import ToolError

HF_BLOCKLIST = ("huggingface.co", "*.huggingface.co", "hf.co", "*.hf.co")


def _make_tool() -> object:
    return create_web_fetch_tool(blocked_hostnames=HF_BLOCKLIST)


@pytest.mark.asyncio
async def test_blocked_hf_host_rejected_before_fetch() -> None:
    tool = _make_tool()
    with pytest.raises(ToolError) as exc_info:
        await tool.ainvoke(
            {
                "urls": ["https://huggingface.co/datasets/leak"],
                "operation": "fetch_full_content",
                "reason": "decontamination probe",
            }
        )
    assert exc_info.value.error_code == "BENCHMARK_BLOCKED_HOST"


@pytest.mark.asyncio
async def test_blocked_short_alias_rejected() -> None:
    tool = _make_tool()
    with pytest.raises(ToolError):
        await tool.ainvoke(
            {
                "urls": ["https://hf.co/models/x"],
                "operation": "fetch_full_content",
                "reason": "decontamination probe",
            }
        )


@pytest.mark.asyncio
async def test_blocked_subdomain_rejected() -> None:
    tool = _make_tool()
    with pytest.raises(ToolError):
        await tool.ainvoke(
            {
                "urls": ["https://datasets-server.huggingface.co/rows"],
                "operation": "fetch_full_content",
                "reason": "decontamination probe",
            }
        )


@pytest.mark.asyncio
async def test_clean_url_reaches_fetch_stage() -> None:
    """A public non-blocked URL passes the blocklist; the engine handles it."""
    tool = _make_tool()
    # Patch the engine so the test never touches the network; reaching
    # _fetch_full_content means the blocklist let the URL through.
    import myrm_agent_harness.toolkits.web_fetch.web_fetch_agent_tools as mod

    with patch.object(mod, "_fetch_full_content") as mock_fetch:
        mock_fetch.return_value = {"content": "ok", "metadata": {}}
        result = await tool.ainvoke(
            {
                "urls": ["https://example.com/article"],
                "operation": "fetch_full_content",
                "reason": "probe",
            }
        )
        assert result.get("content") == "ok"
        mock_fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_block_error_text() -> None:
    tool = _make_tool()
    try:
        await tool.ainvoke(
            {
                "urls": ["https://hf.co/x"],
                "operation": "fetch_full_content",
                "reason": "",
            }
        )
    except ToolError as exc:
        assert "URL blocked" in str(exc)
        assert exc.error_category == ToolErrorCategory.BENCHMARK_BLOCKED.value
    else:  # pragma: no cover
        pytest.fail("expected ToolError")
