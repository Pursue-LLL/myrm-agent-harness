"""Unit tests for LanEndpointNoProxyManager and ThinkingModelReasoningAdapter.

Validates RFC 1918 LAN/local proxy bypass detection, thinking model CoT token
scrubbing, reasoning content fallback extraction, and MemoryExtractor integration.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms import (
    LanEndpointNoProxyManager,
    ThinkingModelReasoningAdapter,
)
from myrm_agent_harness.toolkits.memory.strategies.extractor import _parse_response


class TestLanEndpointNoProxyManager:
    """Test suite for local and LAN endpoint detection and proxy bypass configuration."""

    @pytest.mark.parametrize(
        "endpoint, expected",
        [
            ("http://localhost:11434/v1", True),
            ("http://127.0.0.1:8000/api", True),
            ("http://[::1]:11434", True),
            ("http://0.0.0.0:8080", True),
            ("localhost", True),
            ("127.0.0.1", True),
            ("127.0.0.1:11434", True),
            ("http://192.168.1.100:11434/v1", True),
            ("http://10.0.4.15:8000", True),
            ("http://172.16.0.2:11434", True),
            ("http://172.31.255.255:11434", True),
            ("192.168.0.1:8080", True),
            ("ollama-service.local", True),
            ("http://cluster-node.internal:8000", True),
            ("http://my-nas.lan:5000", True),
            ("http://router.home.arpa:80", True),
            # Public endpoints (should be False)
            ("https://api.openai.com/v1", False),
            ("https://api.anthropic.com/v1", False),
            ("http://8.8.8.8:53", False),
            ("http://1.1.1.1:80", False),
            ("https://172.32.0.1:8000", False),  # Outside RFC 1918 172.16.0.0/12
            ("", False),
            ("   ", False),
        ],
    )
    def test_is_local_or_lan_endpoint(self, endpoint: str, expected: bool) -> None:
        assert LanEndpointNoProxyManager.is_local_or_lan_endpoint(endpoint) is expected

    def test_build_recommended_no_proxy_entries(self) -> None:
        entries = LanEndpointNoProxyManager.build_recommended_no_proxy_entries()
        assert "localhost" in entries
        assert "127.0.0.1" in entries
        assert "10.0.0.0/8" in entries
        assert "172.16.0.0/12" in entries
        assert "192.168.0.0/16" in entries

        custom = LanEndpointNoProxyManager.build_recommended_no_proxy_entries(["192.168.0.0/16", "custom.domain"])
        assert "custom.domain" in custom
        # Verify deduplication
        assert custom.count("192.168.0.0/16") == 1

    def test_configure_bypass_client_kwargs(self) -> None:
        # Local endpoint injects trust_env=False
        kwargs = LanEndpointNoProxyManager.configure_bypass_client_kwargs(
            "http://localhost:11434", {"timeout": 30}
        )
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"] == 30

        # Public endpoint does not modify trust_env
        public_kwargs = LanEndpointNoProxyManager.configure_bypass_client_kwargs(
            "https://api.openai.com", {"timeout": 30}
        )
        assert "trust_env" not in public_kwargs
        assert public_kwargs["timeout"] == 30


class TestThinkingModelReasoningAdapter:
    """Test suite for reasoning model unpacking and <think> token scrubbing."""

    def test_scrub_thinking_tags_closed(self) -> None:
        raw = "<think>\nThinking about preferences...\nUser prefers dark mode.\n</think>\nUser preference: dark mode"
        cleaned = ThinkingModelReasoningAdapter.scrub_thinking_tags(raw)
        assert cleaned == "User preference: dark mode"

    def test_scrub_thinking_tags_unclosed(self) -> None:
        raw = "<think>\nStill reasoning and never closed..."
        cleaned = ThinkingModelReasoningAdapter.scrub_thinking_tags(raw)
        assert cleaned == ""

    def test_scrub_thought_prefix(self) -> None:
        raw = "thought: This is my internal reasoning\n\nActual response here"
        cleaned = ThinkingModelReasoningAdapter.scrub_thinking_tags(raw)
        assert cleaned == "Actual response here"

    def test_extract_effective_content_normal_content(self) -> None:
        payload = {
            "content": "<think>some thought</think>Final extracted content",
            "reasoning_content": "some thought",
        }
        res = ThinkingModelReasoningAdapter.extract_effective_content(payload)
        assert res == "Final extracted content"

    def test_extract_effective_content_fallback_to_reasoning_codeblock(self) -> None:
        # Case: content is empty, reasoning contains a markdown json block
        payload = {
            "content": "",
            "reasoning_content": (
                "Let's output the result in json:\n"
                "```json\n"
                '[{"memory_type": "semantic", "content": "Prefers Python"}]\n'
                "```"
            ),
        }
        res = ThinkingModelReasoningAdapter.extract_effective_content(payload)
        assert res == '[{"memory_type": "semantic", "content": "Prefers Python"}]'

    def test_extract_effective_content_fallback_to_embedded_json(self) -> None:
        payload = {
            "content": "",
            "reasoning": (
                "I should output memory entries now. Here is the array: "
                '[{"memory_type": "semantic", "content": "Lives in Seattle"}]'
                " That is all."
            ),
        }
        res = ThinkingModelReasoningAdapter.extract_effective_content(payload)
        assert res == '[{"memory_type": "semantic", "content": "Lives in Seattle"}]'

    def test_extract_json_block(self) -> None:
        text = "Leading noise [1, 2, 3] trailing noise"
        assert ThinkingModelReasoningAdapter.extract_json_block(text) == "[1, 2, 3]"

        obj_text = 'Noise {"key": "val"} more noise'
        assert ThinkingModelReasoningAdapter.extract_json_block(obj_text) == '{"key": "val"}'

        assert ThinkingModelReasoningAdapter.extract_json_block("No json here") is None
        assert ThinkingModelReasoningAdapter.extract_json_block("") is None


class TestExtractorIntegrationWithThinkingAdapter:
    """Test suite ensuring extractor._parse_response gracefully handles thinking model outputs."""

    def test_parse_response_with_think_tags(self) -> None:
        raw_output = (
            "<think>\n"
            "Analyzing dialogue:\n"
            "- User mentions python experience\n"
            "</think>\n"
            "```json\n"
            "[\n"
            '  {"memory_type": "semantic", "content": "Prefers Python 3.12", "confidence": 0.9}\n'
            "]\n"
            "```"
        )
        memories = _parse_response(raw_output)
        assert len(memories) == 1
        assert memories[0].content == "Prefers Python 3.12"
        assert memories[0].confidence == 0.9

    def test_parse_response_with_embedded_json_in_reasoning(self) -> None:
        raw_output = (
            "Based on the analysis, here is what I found: "
            '[{"memory_type": "semantic", "content": "User works at Acme Corp", "confidence": 0.85}]'
            " Hope this helps!"
        )
        memories = _parse_response(raw_output)
        assert len(memories) == 1
        assert memories[0].content == "User works at Acme Corp"
        assert memories[0].confidence == 0.85
