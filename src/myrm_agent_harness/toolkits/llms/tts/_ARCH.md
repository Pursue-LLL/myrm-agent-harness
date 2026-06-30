# tts/

## Overview

Audio generation module — symmetric with `llms/image/` and `llms/video/`.
Provides text-to-speech via OpenAI and ElevenLabs with Unified Tool Gateway
billing and BYOK fallback.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `models.py` | Config | `TTSConfig`, `TTSResult`, `MediaMeta`, `MediaCallback` | — |
| `generator.py` | Core | `AsyncTTSEngine` — HTTP + gateway failover | ✅ |
| `tts_langchain_tool.py` | Adapter | `TTSTool` + `create_tts_tool()` LangChain factory | ✅ |
| `__init__.py` | Package | Generic engine + optional LangChain exports | — |

## Layering

| Export | Role |
|--------|------|
| `AsyncTTSEngine` + `TTSConfig` | Primary generic API — usable without LangChain |
| `create_tts_tool()` | Optional LangChain adapter for agent tool lists |

Channel outbound TTS (`myrm-agent-server/app/channels/voice/tts.py`) is **business layer** — not part of this module.
