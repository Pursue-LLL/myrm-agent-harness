"""Architecture gate: harness-level prompt rule budget and Turn-1 tool inventory.

Validates (harness scope — 3 checks):
1. Turn-1 default tool profile token overhead (CORE + HIGH_PRIORITY descriptions
   + schema wrappers) does NOT exceed ceiling (≤6500 tokens).
2. Harness system rule constants stay compact: AGENT_CORE_RULES ≤350,
   SECURITY_BOUNDARY_SYSTEM_RULES ≤350, DATETIME_SYSTEM_RULES ≤120.
3. SystemMessage content hash is immutable across multiple resolutions
   (prompt cache safety).

Business-layer CORE prompt caps (full ≤2000 / lean ≤1200 / lean÷full ≤0.70 on
``cl100k_base``) live in the server repo:
``myrm-agent-server/tests/ai_agents/test_prompt_integrity.py::TestPromptTokenBudgetGate``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from myrm_agent_harness.agent.streaming.model_discipline import (
    AGENT_CORE_RULES,
)
from myrm_agent_harness.agent.streaming.utils import (
    DATETIME_SYSTEM_RULES,
)
from myrm_agent_harness.core.security.detection.content_boundary import (
    SECURITY_BOUNDARY_SYSTEM_RULES,
)
from myrm_agent_harness.utils.text_utils import get_token_count
from myrm_agent_harness.utils.token_estimation import (
    estimate_bound_tools_tokens,
)


@pytest.mark.architecture
class TestPromptTokenBudgetGate:
    """CI gate enforcing prompt token budget invariants and prompt cache invariants."""

    @pytest.mark.asyncio
    async def test_turn1_default_tools_token_budget(self) -> None:
        """Assert that Turn-1 default bound tools do not exceed the 6,500 token budget ceiling."""
        from scripts.measure_turn1_token_inventory import _build_default_turn1_tools

        tools = await _build_default_turn1_tools()
        tools_subtotal = estimate_bound_tools_tokens(tools)

        # Baseline is ~5,304 description tokens + 13*65 (845) wrapper = ~6,149 tokens
        # (macOS arm64 host; ~6,123 on Linux where the bash OS hint is shorter).
        # Scope is description + wrapper only — tool parameter schemas are tracked
        # separately in DEFAULT_AGENT_TOKEN_INVENTORY.md §六 (~4,400 for 13 tools).
        # Safe ceiling is 6,500 tokens
        max_allowed_tools_tokens = 6500
        assert (
            tools_subtotal <= max_allowed_tools_tokens
        ), f"Turn-1 default tools token overhead {tools_subtotal} exceeded budget ceiling {max_allowed_tools_tokens}"

    def test_harness_system_prompt_rules_budget(self) -> None:
        """Assert that harness core behavior, security boundary, and datetime rules remain compact."""
        agent_core_tokens = get_token_count(AGENT_CORE_RULES)
        sec_boundary_tokens = get_token_count(SECURITY_BOUNDARY_SYSTEM_RULES)
        datetime_tokens = get_token_count(DATETIME_SYSTEM_RULES)

        # AGENT_CORE_RULES baseline ~240 tokens, ceiling 350 tokens
        assert (
            agent_core_tokens <= 350
        ), f"AGENT_CORE_RULES tokens {agent_core_tokens} exceeded ceiling 350"

        # SECURITY_BOUNDARY_SYSTEM_RULES baseline ~257 tokens, ceiling 350 tokens
        assert (
            sec_boundary_tokens <= 350
        ), f"SECURITY_BOUNDARY_SYSTEM_RULES tokens {sec_boundary_tokens} exceeded ceiling 350"

        # DATETIME_SYSTEM_RULES baseline ~70 tokens, ceiling 120 tokens
        assert (
            datetime_tokens <= 120
        ), f"DATETIME_SYSTEM_RULES tokens {datetime_tokens} exceeded ceiling 120"

    def test_harness_rules_byte_and_hash_stability(self) -> None:
        """Assert that harness system rules are immutable string constants preserving KV cache."""
        from langchain_core.messages import SystemMessage

        from myrm_agent_harness.agent.context_management.infra.cache_break_detector import (
            _compute_system_prompt_hash,
        )

        msg1 = [
            SystemMessage(content=AGENT_CORE_RULES),
            SystemMessage(content=SECURITY_BOUNDARY_SYSTEM_RULES),
            SystemMessage(content=DATETIME_SYSTEM_RULES),
        ]
        msg2 = [
            SystemMessage(content=AGENT_CORE_RULES),
            SystemMessage(content=SECURITY_BOUNDARY_SYSTEM_RULES),
            SystemMessage(content=DATETIME_SYSTEM_RULES),
        ]

        h1 = _compute_system_prompt_hash(msg1)
        h2 = _compute_system_prompt_hash(msg2)
        assert h1 == h2, "System rule hash must be strictly deterministic across calls"
        assert len(h1) == 64
