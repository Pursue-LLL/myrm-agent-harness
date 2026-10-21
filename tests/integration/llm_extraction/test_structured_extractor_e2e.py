"""Real-LLM e2e tests for the structured extraction components.

Both extractors (browser session and evolution skill-capture) route LLM output
through ``extract_answer_text``. These tests exercise the real path without
mocking the LLM.
"""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor import (
    StructuredExtractor as EvolutionExtractor,
)
from myrm_agent_harness.toolkits.browser.session.structured_extractor import (
    StructuredExtractor as BrowserExtractor,
)

pytestmark = pytest.mark.e2e


@pytest.mark.asyncio
async def test_browser_structured_extractor_real_llm(basic_llm) -> None:
    """Browser StructuredExtractor returns schema-compliant JSON from real LLM output."""
    extractor = BrowserExtractor(llm=basic_llm)
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "price": {"type": "string"},
            "stock_status": {"type": "string"},
        },
        "required": ["title"],
    }
    page_text = "iPhone 15 Pro\nPrice: $999\nCurrently in stock, ships within 24 hours."
    result = await extractor.extract(text=page_text, schema=schema)
    assert not result.startswith("[Error]"), f"extraction failed: {result}"
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    assert parsed.get("title"), "title should be extracted from the page text"


@pytest.mark.asyncio
async def test_evolution_structured_extractor_real_llm(basic_llm) -> None:
    """Evolution skill-capture extractor runs end-to-end on a real conversation."""
    extractor = EvolutionExtractor(llm=basic_llm)
    trajectory = (
        "User: How do I fix a 502 Bad Gateway on my nginx server?\n"
        "Assistant: 1. Check `systemctl status nginx`. "
        "2. Verify the upstream is reachable with `curl -I localhost:3000`. "
        "3. If the upstream is down, restart it. "
        "4. Reload nginx with `nginx -s reload`."
    )
    result = await extractor.extract_from_trajectory(trajectory)
    if result is not None:
        assert result.name, "captured skill must have a name"
        assert result.is_general is not None
