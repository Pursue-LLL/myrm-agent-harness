# image/

## Overview
Toolkits Llms Image module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| async_image_engine.py | Core | Async enqueue: writes execution snapshot + prompt into TaskStore; optional `payload_postprocessor` seals secrets before persist (server injects) | ✅ |
| generator.py | Core | Core image generation and editing engine. Wraps LiteLLM's aimage_generation() with Try-Catch Flexible Fallback. | ✅ |
| image_engine.py | Core | Image generation/editing engine class used by server media_tools adapter. | ✅ |
| models.py | Core | Pure data types: ImageResult, ImageGenerationConfig (with gateway_config support), errors. | — |
| types.py | Config | Defines the capability schema for image generation models. | — |
| validator.py | Core | Pre-call validation that rejects invalid image generation requests | ✅ |

## Key Dependencies

- `core`
