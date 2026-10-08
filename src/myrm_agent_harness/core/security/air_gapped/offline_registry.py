"""Local self-contained offline model metadata registry for air-gapped sovereign execution.

[INPUT]
- model_id, OfflineModelMetadata

[OUTPUT]
- OfflineModelRegistry: pre-packaged model context specifications requiring zero external HTTP queries.

[POS]
Harness core security module preventing network hang on LiteLLM/metadata discovery in disconnected environments.
"""

from __future__ import annotations

import threading

from myrm_agent_harness.core.security.air_gapped.types import OfflineModelMetadata

# Static built-in offline registry of prominent sovereign & open-weights models
_BUILTIN_OFFLINE_MODELS: tuple[OfflineModelMetadata, ...] = (
    OfflineModelMetadata(
        model_id="deepseek-r1",
        context_window=65536,
        max_output_tokens=8192,
        tokenizer_type="bpe",
        is_offline_ready=True,
    ),
    OfflineModelMetadata(
        model_id="deepseek-v3",
        context_window=65536,
        max_output_tokens=8192,
        tokenizer_type="bpe",
        is_offline_ready=True,
    ),
    OfflineModelMetadata(
        model_id="qwen2.5-coder-32b",
        context_window=131072,
        max_output_tokens=8192,
        tokenizer_type="tiktoken_cl100k",
        is_offline_ready=True,
    ),
    OfflineModelMetadata(
        model_id="qwen2.5-72b",
        context_window=131072,
        max_output_tokens=8192,
        tokenizer_type="tiktoken_cl100k",
        is_offline_ready=True,
    ),
    OfflineModelMetadata(
        model_id="llama-3.3-70b",
        context_window=131072,
        max_output_tokens=8192,
        tokenizer_type="tiktoken",
        is_offline_ready=True,
    ),
    OfflineModelMetadata(
        model_id="ollama/local",
        context_window=32768,
        max_output_tokens=4096,
        tokenizer_type="generic_offline",
        is_offline_ready=True,
    ),
)


class OfflineModelRegistry:
    """In-memory self-contained registry providing model specs without internet access."""

    def __init__(self) -> None:
        self._registry: dict[str, OfflineModelMetadata] = {
            m.model_id: m for m in _BUILTIN_OFFLINE_MODELS
        }
        self._lock = threading.Lock()

    def get_metadata(self, model_id: str) -> OfflineModelMetadata | None:
        """Fetch specification for a model ID, matching exact name or normalized prefix."""
        clean_id = model_id.strip().lower()
        with self._lock:
            # 1. Exact match
            if clean_id in self._registry:
                return self._registry[clean_id]

            # 2. Substring or prefix match
            for reg_id, meta in self._registry.items():
                if reg_id in clean_id or clean_id in reg_id:
                    return meta

        # Fallback default offline profile
        return OfflineModelMetadata(
            model_id=model_id,
            context_window=32768,
            max_output_tokens=4096,
            tokenizer_type="offline_fallback",
            is_offline_ready=True,
        )

    def register_offline_model(self, metadata: OfflineModelMetadata) -> None:
        """Register or override offline model metadata."""
        with self._lock:
            self._registry[metadata.model_id.lower()] = metadata

    def list_models(self) -> list[OfflineModelMetadata]:
        """List all pre-packaged offline models."""
        with self._lock:
            return list(self._registry.values())
