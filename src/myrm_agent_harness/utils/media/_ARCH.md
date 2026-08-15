# media/

## Overview
Media utilities for image/video compression.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Media utilities for image/video compression. Exports `SEND_COMPRESS_*` constants. | — |
| image_compressor.py | Core | Pure image compression utility. Supports jpg/jpeg/png formats. Includes auto-downsampling (max_dimension) to save LLM tokens, `output_format` forcing (jpeg/png/webp), and `compress_if_needed` — responsive send-time compression with animated GIF/WebP protection (n_frames>1 preserved) and fail-safe fallback to original bytes. `SEND_COMPRESS_*` constants are the SSOT for send-time/upload compression defaults (`trigger_bytes` is measured in base64 space to mirror provider per-image ceilings — Claude API 10 MiB, Bedrock/Vertex/OpenAI 5 MiB, Groq 4 MiB — so a raw-byte check can't let a 4 MiB raw ≈ 5.3 MiB base64 payload past a 5 MiB ceiling); `MAX_DECODE_PIXELS` bounds Pillow's decode guard so decompression-bomb images (tiny files declaring huge canvases) fail fast with `DecompressionBombError` before any pixel allocation. | ✅ |
