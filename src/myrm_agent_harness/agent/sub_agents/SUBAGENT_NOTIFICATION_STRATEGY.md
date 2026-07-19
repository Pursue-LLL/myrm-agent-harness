# Subagent Notification Strategy

## Summary

Subagent completion uses **cache-safe delivery paths**: dynamic content never enters `SystemMessage`; the frozen system prefix stays stable for Prompt Cache.

| Path | Trigger | Delivery | Code |
|------|---------|----------|------|
| In-stream completion | Parent agent still streaming | SSE `SUBAGENT_COMPLETION` only; **no** message injection | `streaming/stream_recovery_continuation.py` |
| Background wakeup | `wait=false` child completes while parent idle | User/HumanMessage with `<system_notification type='async_result'>` + headless rerun | `myrm-agent-server/.../wakeup_handler.py` |
| Active query | LLM needs result details | `subagent_control_tool` (action=list) | `meta_tools/spawn_subagent/` |

---

## Design Rules

1. **No dynamic `SystemMessage`** — subagent results must not append to the SystemMessage chain (see `PROMPT_CACHE_PRACTICE.md` §1253).
2. **In-stream: SSE-only** — `StreamRecoveryContinuation._handle_subagent_notifications()` emits the event and returns `False` (no new turn, no `HumanMessage` append).
3. **Background wakeup: user message** — `ServerWakeupHandler` calls `ChatService.ensure_chat_and_append_user_message()` with wrapped notification text; reloads as HumanMessage on the next run.
4. **LLM retrieval guidance** — system prompt (`sub_agents/prompts.py`) and tool descriptions (`delegate_task_tool`, `subagent_control_tool`) instruct the model to call `subagent_control_tool` (mode=list) for async results.

---

## Prefix Cache Impact

```
Tools → System (frozen) → Messages (dynamic)
                              ↑
                    subagent notifications land here only
```

- Tools + System prefix remain byte-identical across turns when tool list and system chain are stable.
- Wakeup notifications append to **Messages**, so only the tail of the conversation changes.

---

## Related Docs

- [SUB_AGENT_SYSTEM.md](SUB_AGENT_SYSTEM.md) §17 — async wakeup flow
- [PROMPT_CACHE_PRACTICE.md](../context_management/PROMPT_CACHE_PRACTICE.md) — Tools → System → Messages order
