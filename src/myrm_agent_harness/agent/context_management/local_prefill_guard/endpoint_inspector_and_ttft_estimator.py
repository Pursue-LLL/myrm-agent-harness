"""Local inference endpoint introspection and predictive TTFT estimator.

[INPUT]
- local_prefill_types::LocalEndpointKind, LatencyWarningLevel, LocalEndpointProfile, PrefillLatencyEstimate (POS: Local prefill types)

[OUTPUT]
- LocalEndpointInspector: Introspects endpoint parameters and derives hardware profiles.
- TtftLatencyEstimator: Calculates quadratic polynomial TTFT latency estimates.

[POS]
Predictive latency estimation and endpoint detection for local LLMs, predicting
severe prefill stalls (e.g. 64k TTFT reaching 118s on local setups) before LLM dispatch.
"""

from __future__ import annotations

import re
from typing import Mapping

from .local_prefill_types import (
    LatencyWarningLevel,
    LocalEndpointKind,
    LocalEndpointProfile,
    PrefillLatencyEstimate,
)


class LocalEndpointInspector:
    """Introspects endpoint URLs, provider names, and model strings to identify local runtimes."""

    _LOCAL_HOST_PATTERNS = (
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        ".local",
        "host.docker.internal",
    )

    @classmethod
    def inspect(
        cls,
        *,
        base_url: str | None = None,
        model_name: str | None = None,
        provider: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> LocalEndpointProfile:
        """Inspect endpoint attributes and build an inference profile."""
        meta = metadata or {}
        model = str(model_name or meta.get("model") or "unknown-model").strip()
        url = str(base_url or meta.get("base_url") or "").strip().lower()
        prov = str(provider or meta.get("provider") or "").strip().lower()

        # Check explicit override
        if meta.get("is_local") is not None:
            is_local = bool(meta.get("is_local"))
        else:
            is_local = cls._is_local_target(url, prov, model)

        kind = cls._detect_endpoint_kind(url, prov, is_local)
        param_size = cls._estimate_model_params_b(model)
        quant = cls._estimate_quantization(model)

        context_window = int(meta.get("context_window", 65536))
        bandwidth = float(meta.get("memory_bandwidth_gb_s", 400.0))
        is_unified = bool(meta.get("is_unified_memory", True))

        return LocalEndpointProfile(
            endpoint_kind=kind,
            model_name=model,
            is_local=is_local,
            context_window_limit=context_window,
            estimated_param_size_b=param_size,
            quantization=quant,
            memory_bandwidth_gb_s=bandwidth,
            is_unified_memory=is_unified,
        )

    @classmethod
    def _is_local_target(cls, url: str, provider: str, model: str) -> bool:
        if any(h in url for h in cls._LOCAL_HOST_PATTERNS):
            return True
        if any(p in provider for p in ("ollama", "vllm", "mlx", "llama.cpp", "lmstudio", "local")):
            return True
        if any(p in model.lower() for p in (":gguf", "q4_k", "q8_0", "awq", "gptq")):
            return True
        return False

    @classmethod
    def _detect_endpoint_kind(cls, url: str, provider: str, is_local: bool) -> LocalEndpointKind:
        if not is_local:
            return LocalEndpointKind.CLOUD_API
        combo = f"{url} {provider}"
        if "11434" in url or "ollama" in combo:
            return LocalEndpointKind.OLLAMA
        if "vllm" in combo:
            return LocalEndpointKind.VLLM
        if "mlx" in combo:
            return LocalEndpointKind.MLX
        if "1234" in url or "lmstudio" in combo or "lm_studio" in combo:
            return LocalEndpointKind.LM_STUDIO
        if "8080" in url or "llama.cpp" in combo or "llama-cpp" in combo:
            return LocalEndpointKind.LLAMA_CPP
        return LocalEndpointKind.LOCAL_CUSTOM

    @classmethod
    def _estimate_model_params_b(cls, model_name: str) -> float:
        """Extract parameter scale (e.g. 7B, 14B, 32B, 70B) from model tag."""
        match = re.search(r"(\d+(?:\.\d+)?)\s*[bB]", model_name)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        name_lower = model_name.lower()
        if "70b" in name_lower or "67b" in name_lower or "72b" in name_lower:
            return 70.0
        if "32b" in name_lower or "34b" in name_lower or "27b" in name_lower:
            return 32.0
        if "14b" in name_lower or "13b" in name_lower:
            return 14.0
        if "7b" in name_lower or "8b" in name_lower or "9b" in name_lower:
            return 8.0
        return 14.0

    @classmethod
    def _estimate_quantization(cls, model_name: str) -> str:
        name_lower = model_name.lower()
        if "q8" in name_lower:
            return "q8_0"
        if "q4" in name_lower:
            return "q4_k_m"
        if "fp16" in name_lower:
            return "fp16"
        if "int4" in name_lower:
            return "q4_k_m"
        return "q4_k_m"


class TtftLatencyEstimator:
    """Predictive TTFT estimator based on polynomial attention & memory complexity."""

    @classmethod
    def estimate_ttft(
        cls,
        prompt_tokens: int,
        profile: LocalEndpointProfile,
    ) -> PrefillLatencyEstimate:
        """Estimate time-to-first-token in seconds for a given prompt length."""
        tokens = max(prompt_tokens, 0)

        if not profile.is_local or profile.endpoint_kind == LocalEndpointKind.CLOUD_API:
            # Cloud APIs typically have pooled inference clusters with fast prefill
            ttft = 0.4 + (tokens / 10000.0) * 0.35
            warning_lvl = LatencyWarningLevel.NORMAL
            if ttft >= 5.0:
                warning_lvl = LatencyWarningLevel.ELEVATED
            return PrefillLatencyEstimate(
                prompt_tokens=tokens,
                estimated_ttft_seconds=round(ttft, 2),
                warning_level=warning_lvl,
                warning_message=f"Cloud API latency nominal: ~{round(ttft, 2)}s",
                suggests_aggressive_pruning=False,
                quadratic_overhead_fraction=0.05,
            )

        # Local model TTFT modeling
        # Linear term: Memory bandwidth and FFN compute proportional to (params * tokens)
        # Quadratic term: Attention matrix multiplication proportional to tokens^2
        bw_factor = max(profile.memory_bandwidth_gb_s, 100.0) / 400.0
        param_factor = profile.estimated_param_size_b / 14.0

        # Empirical calibration:
        # At 4k on M5 Ultra (bw=400, param=14B): ~0.8s
        # At 32k on M5 Ultra (bw=400, param=14B): ~12.5s
        # At 64k on M5 Ultra (bw=400, param=70B): ~118.0s (Federico Viticci & @sabastod benchmark)
        linear_sec = (tokens / 1000.0) * (0.16 * param_factor / bw_factor)
        quadratic_sec = ((tokens / 1000.0) ** 2) * (0.012 * (param_factor ** 0.8) / bw_factor)

        raw_ttft = linear_sec + quadratic_sec
        # Floor minimal overhead
        estimated_ttft = max(round(raw_ttft, 2), 0.25)

        total_calc = linear_sec + quadratic_sec
        quad_fraction = round(quadratic_sec / max(total_calc, 0.001), 3)

        # Classification thresholds
        if estimated_ttft >= 60.0:
            lvl = LatencyWarningLevel.FREEZE_RISK
            msg = (
                f"Severe stall risk: estimated TTFT {estimated_ttft}s at {tokens} tokens "
                f"(local {profile.endpoint_kind.value} {profile.model_name}). Immediate aggressive pruning required."
            )
        elif estimated_ttft >= 15.0:
            lvl = LatencyWarningLevel.CRITICAL_SLOW
            msg = (
                f"Critical prefill latency: estimated TTFT {estimated_ttft}s at {tokens} tokens. "
                f"Local processing bottleneck detected."
            )
        elif estimated_ttft >= 5.0:
            lvl = LatencyWarningLevel.ELEVATED
            msg = f"Elevated prefill latency: estimated TTFT {estimated_ttft}s at {tokens} tokens."
        else:
            lvl = LatencyWarningLevel.NORMAL
            msg = f"Normal prefill latency: estimated TTFT {estimated_ttft}s."

        suggests_pruning = (
            lvl in (LatencyWarningLevel.CRITICAL_SLOW, LatencyWarningLevel.FREEZE_RISK)
            or tokens >= 32768
        )

        return PrefillLatencyEstimate(
            prompt_tokens=tokens,
            estimated_ttft_seconds=estimated_ttft,
            warning_level=lvl,
            warning_message=msg,
            suggests_aggressive_pruning=suggests_pruning,
            quadratic_overhead_fraction=quad_fraction,
        )
