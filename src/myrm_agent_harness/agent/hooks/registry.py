"""Hook registry — hooks grouped by event, with caller-owned scoped groups.

[INPUT]
- agent.hooks.types (POS: Hook 类型定义)

[OUTPUT]
- HookRegistry: 钩子注册管理器（get() 按 -priority 稳定排序，安全钩子恒定最先；activate_scope/release_scope 让一组钩子的生命周期短于会话）

[POS]
Hook storage layer. Split from the executor so registration lifetime (session vs. run) and execution evolve independently.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from myrm_agent_harness.agent.hooks.types import (
    CallableHookDefinition,
    CommandHookDefinition,
    HookDefinition,
    HttpHookDefinition,
    LLMHookDefinition,
)


class HookRegistry:
    """Store hooks grouped by event name.

    Accepts both HookEvent enum values and arbitrary strings for custom events.
    """

    __slots__ = ("_hooks", "_scopes")

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookDefinition]] = defaultdict(list)
        self._scopes: dict[str, list[tuple[str, HookDefinition]]] = {}

    def register(self, event: str, hook: HookDefinition) -> None:
        self._hooks[event].append(hook)

    def activate_scope(self, scope: str, hooks: Iterable[tuple[str, HookDefinition]]) -> bool:
        """Register ``hooks`` as one named group unless ``scope`` is already active.

        Gives hooks a lifetime shorter than the session registry (for example one
        run). Returns ``False`` and registers nothing when the scope is active
        already: the activation that created it stays its owner, so a nested run
        asking for the same scope neither duplicates the hooks nor removes them
        when it finishes.
        """
        if scope in self._scopes:
            return False
        owned = list(hooks)
        for event, hook in owned:
            self.register(event, hook)
        self._scopes[scope] = owned
        return True

    def release_scope(self, scope: str) -> None:
        """Unregister every hook of ``scope``; an inactive scope is a no-op."""
        for event, hook in self._scopes.pop(scope, ()):
            self._unregister(event, hook)

    def _unregister(self, event: str, hook: HookDefinition) -> None:
        registered = self._hooks.get(event)
        if registered is None:
            return
        # Identity, not equality: two hooks may be equal models yet belong to different scopes.
        for index, candidate in enumerate(registered):
            if candidate is hook:
                del registered[index]
                break
        if not registered:
            del self._hooks[event]

    def get(self, event: str) -> list[HookDefinition]:
        """Return hooks ordered by ``(-priority, registration order)``.

        ``sorted`` is stable, so equal priorities keep the onion-model
        registration order (first registered sees the event first) while
        security-priority hooks always run before user-authored hooks.
        """
        return sorted(self._hooks.get(event, []), key=lambda h: -h.priority)

    def clear(self) -> None:
        self._hooks.clear()
        self._scopes.clear()

    @property
    def total_count(self) -> int:
        return sum(len(hooks) for hooks in self._hooks.values())

    def summary(self) -> str:
        lines: list[str] = []
        for event, hooks in sorted(self._hooks.items()):
            if not hooks:
                continue
            lines.append(f"{event}:")
            for hook in hooks:
                matcher = hook.matcher or "*"
                detail = _hook_detail(hook)
                lines.append(f"  - [{hook.type}] matcher={matcher} {detail}")
        return "\n".join(lines)


def _hook_detail(hook: HookDefinition) -> str:
    if isinstance(hook, CallableHookDefinition):
        fn_name = getattr(hook.fn, "__name__", repr(hook.fn))
        return f"fn={fn_name}"
    if isinstance(hook, CommandHookDefinition):
        return f"cmd={hook.command[:60]}"
    if isinstance(hook, HttpHookDefinition):
        return f"url={hook.url[:60]}"
    if isinstance(hook, LLMHookDefinition):
        return f"depth={hook.depth} prompt={hook.prompt[:40]}"
    return ""
