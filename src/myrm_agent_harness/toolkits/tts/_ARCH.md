# TTS (Text-to-Speech) Toolkit Architecture

## Overview
Provides text-to-speech capabilities for agents, supporting OpenAI and ElevenLabs.
It integrates seamlessly with the Unified Tool Gateway for SaaS billing and BYOK fallback.

## Components

### `models.py`
Defines pure data structures:
- `TTSConfig`: Configuration including `provider`, `model`, `voice`, and `gateway_config`.
- `TTSResult`: Output structure containing audio bytes and persisted URL.
- `MediaMeta` / `MediaCallback`: Interfaces for persisting generated audio.

### `generator.py`
Contains `AsyncTTSEngine`, the core engine that:
- Handles HTTP communication with TTS providers.
- Implements **Try-Catch Flexible Fallback**: If `gateway_config` is enabled but the gateway fails (e.g., 502, 402), it automatically falls back to direct provider API calls using the local `api_key`.

### `tts_tool.py`
Wraps the engine into a LangChain-compatible `TTSTool`.
