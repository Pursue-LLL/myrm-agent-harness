# llms/

## Overview
Toolkits Llms module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| config.py | Config | LiteLLM default configuration (privacy, caching, `drop_params` safety-net). Works with `ChatLiteLLM._inject_allowed_params()` to protect explicit params from provider whitelist gaps | ✅ |
| capability_learner.py | Core | In-process model capability cache — records runtime-discovered capabilities (e.g. rejects_media) with TTL. | ✅ |
| ephemeral_output_tokens.py | Core | ContextVar override for truncation-recovery output budget; read by `ChatLiteLLM`. | ✅ |

| Submodule | Description |
|-----------|-------------|
| batch/ | `llm_map` fan-out engine. See [batch/_ARCH.md](batch/_ARCH.md). |
| consensus/ | Multi-model consensus (MoA) inference — parallel reference queries + aggregator synthesis (arXiv:2406.04692). |
| _media_shared/ | Shared across video/ and image/ modules. Keeps media-specific logic |
| adapters/ | LLM layer: LangChain , messageconverts, handles, toolcallsparse, Schema normalize |
| core/ | LLM core: LLM classes, strategy-aware manager, and credential pool. |
| errors/ | LLM error processing layer: three-tier error classification, fault-tolerant calls, and standardized  |
| fallback/ | Enhanced model fallback management. Contains ManagedLLM with Direct Preflight Guard (zero-cost local token overflow prevention), cooldown periods, candidate pools, and decision logging |
| image/ | Image submodule. |
| providers/ | Providers submodule. |
| routing/ | Routing submodule. |
| utils/ | LLM toollayer: JSON handles, modelparameter, log |
| video/ | Video generation module — multi-provider video generation with failover. |

## Media stack (generation vs understanding)

| Layer | Location | Role |
|-------|----------|------|
| **Generation** | `image/`, `video/` | LLM/agent tools for image and video creation |
| **Shared media** | `_media_shared/` | SSRF-safe fetch, normalization — shared by generation modules |
| **Understanding** | [`../vision/`](../vision/_ARCH.md) | `VisionFallbackEngine` / `VideoAnalysisEngine` — text-mode fallback when the primary model lacks vision; consumed by `file_read_tool`, server chat utils |

Understanding engines live at `toolkits/vision/` today; a future move to `llms/vision/` is optional (import-path only).
