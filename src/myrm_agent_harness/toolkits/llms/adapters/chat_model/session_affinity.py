"""Session affinity for ChatLiteLLM: keeps one conversation on one provider-side cache.

[INPUT]
- core.context_vars::prompt_routing_key_var, chat_id_var (POS: session-scoped routing key, imported lazily)

[OUTPUT]
- ChatLiteLLMSessionAffinityMixin: first-party endpoint detection (OpenAI / OpenCode / xAI) and per-request routing-key injection

[POS]
Providers route a request to a cache server by a client-supplied key, so sending the session's key with every
request keeps its prompt prefix on the server that already holds it. OpenAI takes `prompt_cache_key`, an OpenCode
relay takes `x-opencode-session`, xAI takes `x-grok-conv-id`. Bound into ``ChatLiteLLM`` by ``model.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse


class ChatLiteLLMSessionAffinityMixin:
    if TYPE_CHECKING:
        # Attributes defined on the ChatLiteLLM aggregate root; declared here so mypy
        # understands the composition-mixin pattern.
        api_base: str | None
        custom_llm_provider: str | None
        model: str

    def _inject_prompt_routing_key(self, params: dict[str, object]) -> None:
        """Inject session-scoped routing keys for KV cache and gateway affinity.

        1. Native OpenAI: injects `prompt_cache_key` into params.
        2. OpenCode relay: injects `x-opencode-session` into `extra_headers`.
        3. Native xAI: injects `x-grok-conv-id` into `extra_headers`, pinning a conversation's
           requests to one cache server so its prompt prefix keeps hitting.
        """
        from myrm_agent_harness.core.context_vars import (
            chat_id_var,
            prompt_routing_key_var,
        )

        routing_key = prompt_routing_key_var.get() or chat_id_var.get()

        # 1. Native OpenAI endpoint affinity
        if routing_key and self._is_openai_native_endpoint():
            params["prompt_cache_key"] = routing_key

        # 2. OpenCode relay endpoint session affinity
        if self._is_opencode_endpoint():
            session_val = routing_key or "sess-default-open-affinity"
            raw_headers = params.get("extra_headers")
            extra_headers: dict[str, str] = dict(raw_headers) if isinstance(raw_headers, dict) else {}
            if not any(k.lower() == "x-opencode-session" for k in extra_headers):
                extra_headers["x-opencode-session"] = session_val
                params["extra_headers"] = extra_headers

        # 3. Native xAI endpoint conversation affinity
        if routing_key and self._is_xai_native_endpoint():
            raw_headers = params.get("extra_headers")
            xai_headers: dict[str, str] = dict(raw_headers) if isinstance(raw_headers, dict) else {}
            if not any(k.lower() == "x-grok-conv-id" for k in xai_headers):
                xai_headers["x-grok-conv-id"] = routing_key
                params["extra_headers"] = xai_headers

    def _is_opencode_endpoint(self) -> bool:
        """Detect whether this instance targets an OpenCode relay endpoint."""
        api_base = (self.api_base or "").lower()
        provider = (self.custom_llm_provider or "").lower()
        model = (self.model or "").lower()
        return "opencode.ai" in api_base or provider.startswith("opencode") or "opencode" in model

    def _is_xai_native_endpoint(self) -> bool:
        """Detect whether this instance targets the first-party xAI API (incl. its regional hosts)."""
        api_base = (self.api_base or "").strip().lower()
        if api_base:
            host = urlparse(api_base if "://" in api_base else f"//{api_base}").hostname or ""
            return host == "x.ai" or host.endswith(".x.ai")
        provider = (self.custom_llm_provider or "").lower()
        return provider == "xai" or (self.model or "").lower().startswith("xai/")

    def _is_openai_native_endpoint(self) -> bool:
        """Detect whether this instance targets a native OpenAI API endpoint."""
        api_base = (self.api_base or "").lower()
        provider = (self.custom_llm_provider or "").lower()

        if provider and provider != "openai":
            return False

        return bool(not api_base or "api.openai.com" in api_base)
