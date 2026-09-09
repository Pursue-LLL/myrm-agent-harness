"""Unit tests for agent/config/litellm_routing.py."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.config.litellm_routing import (
    known_litellm_route_segments_ordered,
    litellm_route_prefix_for_effective,
    normalize_env_model_selection_string,
)


class TestLitellmRoutePrefixForEffective:
    def test_openai_family(self) -> None:
        assert litellm_route_prefix_for_effective("openai") == "openai/"
        assert litellm_route_prefix_for_effective("siliconflow") == "openai/"
        assert litellm_route_prefix_for_effective("openai-like") == "openai/"
        assert litellm_route_prefix_for_effective("openai_compatible") == "openai/"
        assert litellm_route_prefix_for_effective("spark") == "openai/"
        assert litellm_route_prefix_for_effective("vercel_ai_gateway") == "openai/"

    def test_gemini_family(self) -> None:
        assert litellm_route_prefix_for_effective("gemini-like") == "gemini/"
        assert litellm_route_prefix_for_effective("gemini_compatible") == "gemini/"

    def test_anthropic_family(self) -> None:
        assert litellm_route_prefix_for_effective("anthropic-like") == "anthropic/"
        assert litellm_route_prefix_for_effective("anthropic_compatible") == "anthropic/"

    def test_other_vendors(self) -> None:
        assert litellm_route_prefix_for_effective("minimax") == "minimax/"
        assert litellm_route_prefix_for_effective("xiaomi_mimo") == "xiaomi_mimo/"
        assert litellm_route_prefix_for_effective("custom_vendor") == "custom_vendor/"


class TestNormalizeEnvModelSelectionString:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("gpt-4o-mini", "gpt-4o-mini"),
            ("openai-like/mimo-x", "openai/mimo-x"),
            ("openai-compatible/deepseek", "openai/deepseek"),
            ("openai_compatible/deepseek", "openai/deepseek"),
            ("siliconflow/Qwen/Qwen3-235B-A22B", "openai/Qwen/Qwen3-235B-A22B"),
            ("gemini-like/foo", "gemini/foo"),
            ("anthropic-like/bar", "anthropic/bar"),
            ("xiaomi_mimo/mimo-1", "xiaomi_mimo/mimo-1"),
            ("xiaomi/legacy", "xiaomi_mimo/legacy"),
            ("volcengine/unchanged", "volcengine/unchanged"),
        ],
    )
    def test_cases(self, raw: str, expected: str) -> None:
        assert normalize_env_model_selection_string(raw) == expected

    def test_strips_whitespace(self) -> None:
        assert normalize_env_model_selection_string("  openai-like/foo  ") == "openai/foo"


class TestConstantsExport:
    """契约：与前端生成器共享的字典键集合稳定。"""

    def test_builtin_maps(self) -> None:
        from myrm_agent_harness.agent.config.litellm_routing import (
            BUILTIN_PROVIDER_LITELLM_SEGMENT,
            CUSTOM_COMPAT_TYPE_LITELLM_SEGMENT,
        )

        assert BUILTIN_PROVIDER_LITELLM_SEGMENT["siliconflow"] == "openai"
        assert BUILTIN_PROVIDER_LITELLM_SEGMENT["xiaomi_mimo"] == "xiaomi_mimo"
        assert BUILTIN_PROVIDER_LITELLM_SEGMENT["vercel_ai_gateway"] == "openai"
        assert set(CUSTOM_COMPAT_TYPE_LITELLM_SEGMENT.keys()) == {
            "openai-like",
            "gemini-like",
            "anthropic-like",
        }

    def test_ordered_nonempty(self) -> None:
        segs = known_litellm_route_segments_ordered()
        assert "openai" in segs
        assert "xiaomi_mimo" in segs
        lengths = [len(s) for s in segs]
        assert lengths == sorted(lengths, reverse=True)


class TestOpenCodeSessionAffinity:
    """验证 OpenCode 网关的会话亲和性请求头自动注入机制。"""

    def test_opencode_affinity_header_injected(self) -> None:
        from myrm_agent_harness.core.context_vars import prompt_routing_key_var
        from myrm_agent_harness.toolkits.llms.core.llm import ChatLiteLLM

        token = prompt_routing_key_var.set("test-sess-123")
        try:
            llm = ChatLiteLLM(
                model="openai/deepseek-v4-flash",
                api_base="https://opencode.ai/zen/go/v1",
                api_key="test-key",
            )
            params: dict[str, object] = {}
            llm._inject_prompt_routing_key(params)
            assert "extra_headers" in params
            assert isinstance(params["extra_headers"], dict)
            assert params["extra_headers"]["x-opencode-session"] == "test-sess-123"
        finally:
            prompt_routing_key_var.reset(token)

    def test_existing_header_not_overwritten(self) -> None:
        from myrm_agent_harness.toolkits.llms.core.llm import ChatLiteLLM

        llm = ChatLiteLLM(
            model="openai/deepseek-v4-flash",
            api_base="https://opencode.ai/zen/go/v1",
            api_key="test-key",
        )
        params: dict[str, object] = {"extra_headers": {"x-opencode-session": "custom-session"}}
        llm._inject_prompt_routing_key(params)
        assert params["extra_headers"]["x-opencode-session"] == "custom-session"

    def test_non_opencode_endpoint_untouched(self) -> None:
        from myrm_agent_harness.toolkits.llms.core.llm import ChatLiteLLM

        llm = ChatLiteLLM(
            model="openai/gpt-4o",
            api_base="https://api.openai.com/v1",
            api_key="test-key",
        )
        params: dict[str, object] = {}
        llm._inject_prompt_routing_key(params)
        assert "extra_headers" not in params

