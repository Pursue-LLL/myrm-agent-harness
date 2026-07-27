"""Integration test: Local endpoint timeout relaxation (H05).

Verifies the REAL full chain without mocking:
1. create_litellm_model → ChatLiteLLM instance with correct timeout attributes
2. Remote API call succeeds with default (tight) timeouts
3. Local endpoint detection correctly relaxes stall thresholds

Requires: BASIC_API_KEY, BASIC_BASE_URL, BASIC_MODEL env vars (from .env.test).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.config.litellm_routing import normalize_env_model_selection_string
from myrm_agent_harness.toolkits.llms.core.llm import (
    _LOCAL_FIRST_EVENT_TIMEOUT,
    _LOCAL_INTER_CHUNK_TIMEOUT,
    _LOCAL_REQUEST_TIMEOUT,
    _is_local_endpoint,
    create_litellm_model,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(60)]

_ENV_TEST = Path(__file__).resolve().parents[3] / "myrm-agent" / "myrm-agent-server" / ".env.test"


@pytest.fixture(autouse=True)
def _load_env_test() -> None:
    """Load .env.test to get real API credentials."""
    if not _ENV_TEST.exists():
        pytest.skip(f"{_ENV_TEST} not found")
    for line in _ENV_TEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key and value:
            os.environ.setdefault(key, value)


def _get_basic_llm_config() -> tuple[str, str, str]:
    api_key = os.environ.get("BASIC_API_KEY", "")
    base_url = os.environ.get("BASIC_BASE_URL", "")
    model = os.environ.get("BASIC_MODEL", "")
    if not all([api_key, base_url, model]):
        pytest.skip("BASIC_API_KEY/BASIC_BASE_URL/BASIC_MODEL not configured")
    model = normalize_env_model_selection_string(model)
    return api_key, base_url, model


class TestLocalEndpointDetectionRealChain:
    """Full-chain: create_litellm_model produces real ChatLiteLLM with correct timeouts."""

    def test_remote_endpoint_preserves_defaults(self) -> None:
        """Remote endpoint: ChatLiteLLM instance keeps tight defaults (60s first_event)."""
        api_key, base_url, model = _get_basic_llm_config()

        llm = create_litellm_model(model, base_url=base_url, api_key=api_key, streaming=True)

        assert llm.first_event_timeout == 60.0
        assert llm.inter_chunk_timeout == 180.0
        assert llm.request_timeout == 300.0

    def test_local_endpoint_relaxes_all_timeouts(self) -> None:
        """Local endpoint: ChatLiteLLM instance receives relaxed timeouts."""
        llm = create_litellm_model(
            "llama-3.1-70b",
            base_url="http://localhost:11434",
            api_key="ollama",
            streaming=True,
        )

        assert llm.first_event_timeout == _LOCAL_FIRST_EVENT_TIMEOUT
        assert llm.inter_chunk_timeout == _LOCAL_INTER_CHUNK_TIMEOUT
        assert llm.request_timeout == _LOCAL_REQUEST_TIMEOUT

    def test_private_network_192_168_relaxes(self) -> None:
        """192.168.x.x endpoint: treated as local."""
        llm = create_litellm_model(
            "qwen2.5-72b",
            base_url="http://192.168.1.100:11434",
            api_key="local",
            streaming=True,
        )

        assert llm.first_event_timeout == _LOCAL_FIRST_EVENT_TIMEOUT
        assert llm.inter_chunk_timeout == _LOCAL_INTER_CHUNK_TIMEOUT
        assert llm.request_timeout == _LOCAL_REQUEST_TIMEOUT

    def test_reasoning_model_on_remote_applies_floor(self) -> None:
        """Reasoning model (o3) on remote: reasoning floor applied."""
        api_key, base_url, _ = _get_basic_llm_config()

        llm = create_litellm_model("o3", base_url=base_url, api_key=api_key, streaming=True)

        assert llm.request_timeout == 600.0
        assert llm.first_event_timeout == 300.0

    def test_reasoning_model_on_local_combines_floors(self) -> None:
        """Reasoning model on local: reasoning floor overrides local defaults (higher priority)."""
        llm = create_litellm_model(
            "deepseek-r1",
            base_url="http://localhost:11434",
            api_key="local",
            streaming=True,
        )

        assert llm.request_timeout == 600.0
        assert llm.first_event_timeout == 300.0
        assert llm.inter_chunk_timeout == _LOCAL_INTER_CHUNK_TIMEOUT

    def test_user_explicit_timeout_overrides_all(self) -> None:
        """User-provided timeouts take precedence over both local and reasoning logic."""
        llm = create_litellm_model(
            "deepseek-r1",
            base_url="http://localhost:11434",
            api_key="local",
            streaming=True,
            first_event_timeout=120.0,
            inter_chunk_timeout=240.0,
            request_timeout=900.0,
        )

        assert llm.first_event_timeout == 120.0
        assert llm.inter_chunk_timeout == 240.0
        assert llm.request_timeout == 900.0


class TestEdgeCaseEndpoints:
    """Edge cases: IPv6, various port numbers, URL paths, 10.x, 172.x boundaries."""

    def test_ipv6_localhost_relaxes(self) -> None:
        """IPv6 loopback [::1] is detected as local."""
        llm = create_litellm_model(
            "llama-3.1-8b",
            base_url="http://[::1]:11434",
            api_key="local",
            streaming=True,
        )

        assert llm.first_event_timeout == _LOCAL_FIRST_EVENT_TIMEOUT
        assert llm.inter_chunk_timeout == _LOCAL_INTER_CHUNK_TIMEOUT
        assert llm.request_timeout == _LOCAL_REQUEST_TIMEOUT

    def test_10_network_detected_as_local(self) -> None:
        """10.x.x.x (Class A private) is detected as local."""
        llm = create_litellm_model(
            "qwen2.5-32b",
            base_url="http://10.0.1.5:8080/v1",
            api_key="local",
            streaming=True,
        )

        assert llm.first_event_timeout == _LOCAL_FIRST_EVENT_TIMEOUT

    def test_172_16_boundary_detected_as_local(self) -> None:
        """172.16.0.0/12 private range is detected as local."""
        llm = create_litellm_model(
            "qwen2.5-32b",
            base_url="http://172.16.0.1:11434",
            api_key="local",
        )

        assert llm.first_event_timeout == _LOCAL_FIRST_EVENT_TIMEOUT

    def test_172_32_not_local(self) -> None:
        """172.32.x.x is outside private range, NOT detected as local."""
        llm = create_litellm_model(
            "gpt-4o",
            base_url="http://172.32.0.1:8080",
            api_key="sk-test",
            streaming=True,
        )

        assert llm.first_event_timeout == 60.0
        assert llm.request_timeout == 300.0

    def test_url_with_path_detected(self) -> None:
        """URL with /v1 path suffix still correctly detects local host."""
        llm = create_litellm_model(
            "llama-3.1-70b",
            base_url="http://127.0.0.1:1234/v1",
            api_key="lmstudio",
            streaming=True,
        )

        assert llm.first_event_timeout == _LOCAL_FIRST_EVENT_TIMEOUT
        assert llm.inter_chunk_timeout == _LOCAL_INTER_CHUNK_TIMEOUT

    def test_cgnat_100_64_not_local(self) -> None:
        """100.64.x.x (CGNAT/Tailscale) is NOT RFC1918 private, not relaxed."""
        llm = create_litellm_model(
            "gpt-4o",
            base_url="http://100.64.0.1:11434",
            api_key="sk-test",
            streaming=True,
        )

        assert llm.first_event_timeout == 60.0

    def test_no_base_url_uses_defaults(self) -> None:
        """No base_url provided: no detection triggered, default timeouts."""
        llm = create_litellm_model("gpt-4o", api_key="sk-test", streaming=True)

        assert llm.first_event_timeout == 60.0
        assert llm.inter_chunk_timeout == 180.0
        assert llm.request_timeout == 300.0

    def test_zero_zero_zero_zero_detected_as_local(self) -> None:
        """0.0.0.0 binding address is treated as local."""
        llm = create_litellm_model(
            "llama-3.1-8b",
            base_url="http://0.0.0.0:11434",
            api_key="local",
            streaming=True,
        )

        assert llm.first_event_timeout == _LOCAL_FIRST_EVENT_TIMEOUT


class TestTimeoutPropagationToLiteLLM:
    """Verify timeout values actually reach litellm layer (spy, no full mock)."""

    def test_force_timeout_equals_request_timeout(self) -> None:
        """ChatLiteLLM._default_params['force_timeout'] matches request_timeout."""
        llm = create_litellm_model(
            "llama-3.1-70b",
            base_url="http://localhost:11434",
            api_key="ollama",
            streaming=True,
        )

        params = llm._default_params
        assert params["force_timeout"] == _LOCAL_REQUEST_TIMEOUT

    def test_remote_force_timeout_default(self) -> None:
        """Remote endpoint: force_timeout = default 300s."""
        api_key, base_url, model = _get_basic_llm_config()

        llm = create_litellm_model(model, base_url=base_url, api_key=api_key)

        params = llm._default_params
        assert params["force_timeout"] == 300.0

    def test_reasoning_floor_propagates_to_force_timeout(self) -> None:
        """Reasoning model: force_timeout = reasoning floor (600s)."""
        llm = create_litellm_model("o3", api_key="sk-test")

        params = llm._default_params
        assert params["force_timeout"] == 600.0


class TestRemoteApiRealCall:
    """Full-chain: verify remote API actually responds within tight default timeouts."""

    @pytest.mark.asyncio
    async def test_remote_api_streaming_within_default_timeout(self) -> None:
        """Real API call with default timeouts succeeds (proves tight defaults work for cloud)."""
        api_key, base_url, model = _get_basic_llm_config()

        llm = create_litellm_model(model, base_url=base_url, api_key=api_key, streaming=True)

        assert llm.first_event_timeout == 60.0

        result = await llm.ainvoke([HumanMessage(content="Reply with exactly: OK")])
        assert result is not None
        assert isinstance(result, (HumanMessage, type(result)))
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_remote_api_non_streaming_within_default_timeout(self) -> None:
        """Non-streaming real call with default request_timeout=300s succeeds."""
        api_key, base_url, model = _get_basic_llm_config()

        llm = create_litellm_model(model, base_url=base_url, api_key=api_key, streaming=False)

        assert llm.request_timeout == 300.0

        result = await llm.ainvoke([HumanMessage(content="Reply with exactly one word: hello")])
        assert result is not None
        assert len(result.content) > 0
