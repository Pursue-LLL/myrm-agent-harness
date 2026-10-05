"""Cross-layer context variables shared by both agent/ and toolkits/.

ContextVars defined here can be safely imported from any layer without
introducing forbidden dependencies (e.g. toolkits/ → agent/).

[INPUT]
- (none — pure stdlib ContextVar definitions)

[OUTPUT]
- user_timezone_var: User timezone string (e.g. "Asia/Shanghai")
- datetime_injection_enabled_var: Whether to inject timestamps into messages
- prompt_routing_key_var: Session-scoped routing key for OpenAI prompt cache affinity
- workspace_root_var: Sandbox workspace root for toolkit spill paths
- chat_id_var: Active chat/session id for per-session spill directories
- approval_session_var: Approval-routing session key shared by agent/ and toolkits/
- protected_paths_var: Goal-scoped protected path patterns every write channel must honour

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

workspace_root_var: ContextVar[str] = ContextVar("workspace_root", default="")
chat_id_var: ContextVar[str] = ContextVar("chat_id", default="")

# Approval-routing session key. Held here rather than in
# agent/middlewares/_session_context so the sandbox executor can resolve the
# active approval session without depending on agent/; the agent accessor
# keeps ``get_approval_session`` / ``set_approval_session`` for its callers.
approval_session_var: ContextVar[str] = ContextVar("approval_session_key", default="")

# Goal-scoped protected path patterns. Held here rather than in
# agent/middlewares/_session_context so the sandbox executor can enforce the same
# rules as the file tools and the shell pre-flight without depending on agent/.
protected_paths_var: ContextVar[tuple[str, ...]] = ContextVar("protected_paths", default=())
