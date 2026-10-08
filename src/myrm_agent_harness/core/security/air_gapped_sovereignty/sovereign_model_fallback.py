"""
[POS] src/myrm_agent_harness/core/security/air_gapped_sovereignty/sovereign_model_fallback.py
[INPUT] threading, typing, .types (ModelFallbackTarget, NetworkConnectivityModeEnum)
[OUTPUT] SovereignModelFallbackManager

Manages sovereign model fallback strategies, air-gapped network mode transitions,
and automatic degradation failover to local sovereign weights (e.g., Ollama / vLLM).
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading

from .types import ModelFallbackTarget, NetworkConnectivityModeEnum


class SovereignModelFallbackManager:
    """Coordinates runtime model resolution under online, air-gapped, and degraded conditions."""

    def __init__(
        self,
        initial_mode: NetworkConnectivityModeEnum = NetworkConnectivityModeEnum.AIR_GAPPED_ISOLATED,
        default_sovereign_target: ModelFallbackTarget | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._mode = initial_mode
        self._default_sovereign = default_sovereign_target or ModelFallbackTarget(
            model_id="qwen2.5-coder:32b",
            endpoint_url="http://127.0.0.1:11434/v1",
            provider="ollama",
            is_local_sovereign=True,
            context_window=32768,
        )
        self._targets: dict[str, ModelFallbackTarget] = {
            self._default_sovereign.model_id: self._default_sovereign
        }
        self._fallback_count = 0

    @property
    def fallback_count(self) -> int:
        """Total number of times a fallback was triggered."""
        with self._lock:
            return self._fallback_count

    def get_mode(self) -> NetworkConnectivityModeEnum:
        """Return current network connectivity mode."""
        with self._lock:
            return self._mode

    def set_mode(self, mode: NetworkConnectivityModeEnum) -> None:
        """Update network connectivity mode."""
        with self._lock:
            self._mode = mode

    def register_fallback_target(self, target: ModelFallbackTarget) -> None:
        """Register a recognized fallback target."""
        with self._lock:
            self._targets[target.model_id] = target

    def get_target(self, model_id: str) -> ModelFallbackTarget | None:
        """Retrieve target configuration by model id."""
        with self._lock:
            return self._targets.get(model_id)

    def resolve_effective_target(
        self,
        requested_model_id: str,
        is_remote_healthy: bool = True,
    ) -> tuple[ModelFallbackTarget, bool, str]:
        """Resolve effective model execution target according to network policy.

        Returns:
            Tuple of (effective_target, was_fallback, explanation)
        """
        with self._lock:
            # 1. Air-Gapped Mode: Strictly sovereign local models allowed
            if self._mode == NetworkConnectivityModeEnum.AIR_GAPPED_ISOLATED:
                target = self._targets.get(requested_model_id)
                if target is not None and target.is_local_sovereign:
                    return target, False, "Air-gapped local sovereign model verified."

                self._fallback_count += 1
                return (
                    self._default_sovereign,
                    True,
                    (
                        f"Air-gapped enforcement: Requested model '{requested_model_id}' "
                        f"diverted to sovereign local model '{self._default_sovereign.model_id}'."
                    ),
                )

            # 2. Degraded Failover Mode: Always prioritize local fallback
            if self._mode == NetworkConnectivityModeEnum.DEGRADED_FAILOVER:
                self._fallback_count += 1
                return (
                    self._default_sovereign,
                    True,
                    (
                        f"System in degraded failover state. Diverted '{requested_model_id}' "
                        f"to local sovereign target '{self._default_sovereign.model_id}'."
                    ),
                )

            # 3. Online Mode: Direct if remote healthy, failover if unhealthy
            if not is_remote_healthy:
                self._mode = NetworkConnectivityModeEnum.DEGRADED_FAILOVER
                self._fallback_count += 1
                return (
                    self._default_sovereign,
                    True,
                    (
                        f"Remote model '{requested_model_id}' unreachable or degraded. "
                        f"Automatically transitioned to {self._default_sovereign.model_id}."
                    ),
                )

            # Online and healthy
            existing = self._targets.get(requested_model_id)
            if existing is not None:
                return existing, False, f"Direct online dispatch to '{requested_model_id}'."

            # Dynamic placeholder for online remote model
            dynamic_remote = ModelFallbackTarget(
                model_id=requested_model_id,
                endpoint_url="https://api.openai.com/v1",
                provider="remote_provider",
                is_local_sovereign=False,
                context_window=128000,
            )
            return dynamic_remote, False, f"Dispatching to remote endpoint '{requested_model_id}'."
