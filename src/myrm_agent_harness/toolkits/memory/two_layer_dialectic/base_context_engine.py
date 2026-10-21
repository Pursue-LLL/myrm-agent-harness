"""
[INPUT]
models.py (BaseContextBundle, DialecticCadenceConfig)

[OUTPUT]
BaseContextEngine: Generates and caches low-frequency Layer 1 Base Context bundles.
Mounts context onto User Message tail to guarantee 100% frozen System Prompt KV Cache.

[POS]
Layer 1 Core Engine for Two-Layer Context Injection & Multi-Pass Dialectic Reconciliation Suite.
Strict typing applied: No `Any` types allowed. Single file < 250 lines.
"""

from myrm_agent_harness.toolkits.memory.two_layer_dialectic.models import (
    BaseContextBundle,
    DialecticCadenceConfig,
)


class BaseContextEngine:
    """Layer 1 engine: generates and manages cadence-governed Base Context bundles.

    Protects System Prompt KV Cache by delegating contextual injections exclusively
    to the tail of User Message payloads.
    """

    def __init__(self, config: DialecticCadenceConfig | None = None) -> None:
        self._config = config or DialecticCadenceConfig()
        # session_id -> cached BaseContextBundle
        self._bundle_cache: dict[str, BaseContextBundle] = {}

    @property
    def config(self) -> DialecticCadenceConfig:
        """Active cadence configuration."""
        return self._config

    def should_refresh_base_context(self, session_id: str, current_turn: int) -> bool:
        """Determine whether the cached base context has expired based on cadence."""
        cached = self._bundle_cache.get(session_id)
        if cached is None:
            return True
        turn_diff = current_turn - cached.generation_turn
        return turn_diff >= self._config.context_cadence

    def get_or_generate_bundle(
        self,
        session_id: str,
        current_turn: int,
        session_summary: str,
        peer_card_summary: str,
        force_refresh: bool = False,
    ) -> BaseContextBundle:
        """Retrieve existing cached bundle or build a fresh bundle if cadence elapsed."""
        if not force_refresh and not self.should_refresh_base_context(session_id, current_turn):
            return self._bundle_cache[session_id]

        # Calculate lightweight token estimation (~4 chars/token heuristic)
        combined_text = f"{session_summary} {peer_card_summary}"
        estimated_tokens = max(15, len(combined_text) // 4)

        bundle = BaseContextBundle(
            session_id=session_id,
            session_summary=session_summary.strip(),
            peer_card_summary=peer_card_summary.strip(),
            generation_turn=current_turn,
            cadence_interval=self._config.context_cadence,
            estimated_tokens=estimated_tokens,
            system_prompt_frozen=True,
        )
        bundle.tail_injection_xml = bundle.formatted_user_tail_block()
        self._bundle_cache[session_id] = bundle
        return bundle

    def inject_into_user_message(
        self,
        raw_user_message: str,
        bundle: BaseContextBundle,
    ) -> str:
        """Inject base context into user message tail, keeping System Prompt pristine.

        Args:
            raw_user_message: Original user message text.
            bundle: Base context bundle to append.

        Returns:
            Appended user message with structured base context XML tag.
        """
        injection = bundle.formatted_user_tail_block()
        return f"{raw_user_message.rstrip()}{injection}"

    def get_cached_bundle(self, session_id: str) -> BaseContextBundle | None:
        """Inspect currently cached bundle without refreshing."""
        return self._bundle_cache.get(session_id)

    def invalidate(self, session_id: str) -> None:
        """Explicitly clear cached bundle for a session."""
        self._bundle_cache.pop(session_id, None)

    def clear_all(self) -> None:
        """Clear all session bundle caches."""
        self._bundle_cache.clear()
