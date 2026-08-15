# media/

## Overview
Media utilities for image/video compression.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Media utilities for image/video compression. Exports `SEND_COMPRESS_*` constants. | — |
| image_compressor.py | Core | Pure image compression utility. Supports jpg/jpeg/png formats. Includes auto-downsampling (max_dimension) to save LLM tokens, `output_format` forcing (jpeg/png/webp), and `compress_if_needed` — responsive send-time compression with animated-GIF protection and fail-safe fallback to original bytes. `SEND_COMPRESS_*` constants are the SSOT for send-time/upload compression defaults. | ✅ |
