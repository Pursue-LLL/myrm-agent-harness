# image/

## Overview

Image generation and editing. Sync path: `generator.py` / `image_engine.py`. Async path:
`async_image_engine.py` enqueues via `toolkits/tasks/` — full chain in
[TASK_QUEUE_SYSTEM.md](../../tasks/TASK_QUEUE_SYSTEM.md).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| async_image_engine.py | Core | Async enqueue: writes execution snapshot + prompt into TaskStore; optional `payload_postprocessor` seals secrets before persist (server injects) | ✅ |
| generator.py | Core | Core image generation and editing engine. Wraps LiteLLM's aimage_generation() with Try-Catch Flexible Fallback. | ✅ |
| image_engine.py | Core | Image generation/editing engine class used by server media_tools adapter. | ✅ |
| models.py | Core | Pure data types: ImageResult, ImageGenerationConfig (with gateway_config support), errors. | — |
| types.py | Config | Defines the capability schema for image generation models. | — |
| validator.py | Core | 3-layer pre-call validation (L1 prompt, L2 capability, L3 input MIME/size). URL SSRF at `secure_get` download time | ✅ |

## Key Dependencies

- `core.security.http.secure_fetch` (secure_get for reference image and result URL downloads)
- `core`
