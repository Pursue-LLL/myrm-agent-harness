"""Dual-Layer Memory Weaver for Custom Agent Persona and Shared Global Context.

Weaves custom agent private memories with shared global preferences while
preventing cross-agent leakage and respecting token budget caps.

[INPUT]
- memory.context_hook_pipeline.models::{DualLayerMemoryPayload, MemoryFragment, MemoryLayerKind} (POS: Data contracts of the context hook pipeline package)

[OUTPUT]
- WeavingOutcome: the woven Markdown block, how many private and shared fragments it holds and its estimated token cost
- DualLayerMemoryWeaver: keeps private fragments that are ownerless or belong to the target agent, ranks both layers by weight and fills the token budget private-first, then with shared fragments

[POS]
Dual-layer memory weaver of the context hook pipeline package. Selects private and shared fragments within a token budget and renders the block the facade injects into the envelope.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.context_hook_pipeline.models import (
    DualLayerMemoryPayload,
    MemoryFragment,
    MemoryLayerKind,
)


class WeavingOutcome:
    """Result of dual-layer memory weaving."""

    __slots__ = ("estimated_tokens", "private_count", "shared_count", "woven_block")

    def __init__(
        self,
        woven_block: str,
        private_count: int,
        shared_count: int,
        estimated_tokens: int,
    ) -> None:
        self.woven_block = woven_block
        self.private_count = private_count
        self.shared_count = shared_count
        self.estimated_tokens = estimated_tokens


class DualLayerMemoryWeaver:
    """Weaves private agent memories and shared global context with strict isolation."""

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count: roughly 1.5 tokens per Chinese character or 0.25 per ASCII char."""
        cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - cjk_chars
        return int(cjk_chars * 1.5 + (other_chars / 4.0)) + 1

    def weave(self, payload: DualLayerMemoryPayload) -> WeavingOutcome:
        """Weave private and shared memory fragments into an authoritative context block."""
        target_agent = payload.agent_id
        budget = payload.max_token_budget

        # 1. Filter and isolate private fragments (strict boundary check)
        valid_privates: list[MemoryFragment] = [
            f for f in payload.private_fragments
            if f.layer == MemoryLayerKind.PRIVATE_AGENT and (f.agent_id is None or f.agent_id == target_agent)
        ]
        # Sort private by weight descending
        valid_privates.sort(key=lambda f: f.weight, reverse=True)

        # 2. Filter shared fragments
        valid_shared: list[MemoryFragment] = [
            f for f in payload.shared_fragments
            if f.layer == MemoryLayerKind.SHARED_GLOBAL
        ]
        # Sort shared by weight descending
        valid_shared.sort(key=lambda f: f.weight, reverse=True)

        selected_privates: list[MemoryFragment] = []
        selected_shared: list[MemoryFragment] = []
        accumulated_tokens = 0

        # 3. Private-First Allocation: Reserve up to 70% budget for private agent memories
        private_budget = int(budget * 0.70)
        for pf in valid_privates:
            cost = self._estimate_tokens(pf.content)
            if accumulated_tokens + cost <= private_budget:
                selected_privates.append(pf)
                accumulated_tokens += cost
            elif accumulated_tokens + cost <= budget:
                # Still within total budget if shared doesn't use it
                selected_privates.append(pf)
                accumulated_tokens += cost

        # 4. Shared Allocation: Fill remaining budget with shared global memories
        for sf in valid_shared:
            cost = self._estimate_tokens(sf.content)
            if accumulated_tokens + cost <= budget:
                selected_shared.append(sf)
                accumulated_tokens += cost

        # 5. Format assembled Markdown memory block
        lines: list[str] = [
            f"### 【智能体专属与全局双层记忆注入 (Agent: {target_agent})】",
        ]

        if selected_privates:
            lines.append("- **智能体私有知识与专属设定 (Private Scoped)**:")
            for p in selected_privates:
                tag_str = f" [{', '.join(p.tags)}]" if p.tags else ""
                lines.append(f"  - {p.content}{tag_str}")

        if selected_shared:
            lines.append("- **全局共享规范与通用偏好 (Shared Global)**:")
            for s in selected_shared:
                tag_str = f" [{', '.join(s.tags)}]" if s.tags else ""
                lines.append(f"  - {s.content}{tag_str}")

        assembled_str = "\n".join(lines)
        final_token_est = self._estimate_tokens(assembled_str)

        return WeavingOutcome(
            woven_block=assembled_str,
            private_count=len(selected_privates),
            shared_count=len(selected_shared),
            estimated_tokens=final_token_est,
        )
