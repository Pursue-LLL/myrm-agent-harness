"""Cross-layer context variables shared by both agent/ and toolkits/.

ContextVars defined here can be safely imported from any layer without
introducing forbidden dependencies (e.g. toolkits/ → agent/).

[INPUT]
- (none — pure stdlib ContextVar definitions)

[OUTPUT]
- user_timezone_var: User timezone string (e.g. "Asia/Shanghai")
- datetime_injection_enabled_var: Whether to inject timestamps into messages
- prompt_routing_key_var: Session-scoped routing key for OpenAI prompt cache affinity

[POS]
Foundation ContextVar registry. Eliminates coupling between agent/ and toolkits/
by providing a neutral location for runtime context that both layers need.
"""

from __future__ import annotations

from contextvars import ContextVar

user_timezone_var: ContextVar[str | None] = ContextVar("user_timezone", default=None)
datetime_injection_enabled_var: ContextVar[bool] = ContextVar("datetime_injection_enabled", default=True)

# OpenAI prompt_cache_key routing hint — set per-session to maximize KV cache hit
# rate by ensuring requests from the same session route to the same inference node.
prompt_routing_key_var: ContextVar[str | None] = ContextVar("prompt_routing_key", default=None)
