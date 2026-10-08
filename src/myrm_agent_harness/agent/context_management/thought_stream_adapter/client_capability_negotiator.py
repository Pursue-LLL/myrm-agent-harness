"""Client capability negotiator for adaptive determination of reasoning streaming mode.

[INPUT]
- ClientReasoningMode: Target mode enum (REASONING_CONTENT, THINK_TAG_FALLBACK, SILENT).
- ThoughtAdapterConfig: Configuration specifying default modes and behaviors.

[OUTPUT]
- ClientCapabilityNegotiator: Adaptive negotiation engine inspecting headers, user-agents, and payloads.

[POS]
Frontline negotiation guard in the thought streaming adapter ensuring zero-crash compatibility.
"""

from __future__ import annotations

from typing import Mapping

from .thought_adapter_types import ClientReasoningMode, ThoughtAdapterConfig


class ClientCapabilityNegotiator:
    """Negotiates reasoning stream mode dynamically across diverse external AI clients."""

    # Well-known external clients with native SSE delta.reasoning_content support
    NATIVE_REASONING_CLIENTS: tuple[str, ...] = (
        "open-webui",
        "openwebui",
        "librechat",
        "cherry-studio",
        "cherrystudio",
        "nextchat",
        "chatbox",
        "dify",
        "anything-llm",
        "anythingllm",
        "sillytavern",
        "cursor",
        "myrm",
    )

    # Legacy HTTP libraries typically expecting standard OpenAI delta.content only
    LEGACY_HTTP_CLIENTS: tuple[str, ...] = (
        "curl",
        "python-requests",
        "requests/",
        "httpx",
        "aiohttp",
        "postman",
    )

    def __init__(self, config: ThoughtAdapterConfig | None = None) -> None:
        self._config = config or ThoughtAdapterConfig()

    def negotiate(
        self,
        user_agent: str | None = None,
        headers: Mapping[str, str] | None = None,
        request_params: Mapping[str, str | bool | int] | None = None,
    ) -> ClientReasoningMode:
        """Determine optimal reasoning mode based on headers, params, and user-agent.

        Evaluation precedence:
        1. Explicit header overrides ('X-Reasoning-Mode').
        2. Explicit client capability header ('X-Client-Capability').
        3. Request parameter flags ('return_thinking', 'stream_reasoning', 'reasoning_effort').
        4. User-Agent heuristic detection.
        5. Default configuration fallback.
        """
        norm_headers = {k.lower(): v.strip() for k, v in (headers or {}).items()}

        # 1. Direct mode header override
        if "x-reasoning-mode" in norm_headers:
            header_val = norm_headers["x-reasoning-mode"].lower()
            if header_val == "reasoning_content":
                return ClientReasoningMode.REASONING_CONTENT
            if header_val in ("think_tag_fallback", "think_tag", "tag"):
                return ClientReasoningMode.THINK_TAG_FALLBACK
            if header_val in ("silent", "none", "off"):
                return ClientReasoningMode.SILENT

        # 2. Client capability assertion
        if "x-client-capability" in norm_headers:
            caps = norm_headers["x-client-capability"].lower()
            if "reasoning_content" in caps or "thinking" in caps:
                return ClientReasoningMode.REASONING_CONTENT

        # 3. Request body / query parameters
        params = request_params or {}
        if params.get("stream_reasoning") is False or params.get("include_reasoning") is False:
            return ClientReasoningMode.SILENT

        if params.get("reasoning_effort") is not None:
            return ClientReasoningMode.REASONING_CONTENT

        if params.get("return_thinking") is True or params.get("enable_thinking") is True:
            return ClientReasoningMode.REASONING_CONTENT

        # 4. User-Agent heuristic
        if user_agent:
            ua_lower = user_agent.lower()
            if any(client in ua_lower for client in self.NATIVE_REASONING_CLIENTS):
                return ClientReasoningMode.REASONING_CONTENT

            if any(legacy in ua_lower for legacy in self.LEGACY_HTTP_CLIENTS):
                return ClientReasoningMode.THINK_TAG_FALLBACK

        # 5. Default configuration fallback
        return self._config.default_mode
