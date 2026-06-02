# providers/

## Overview
Video generation providers — pluggable backends for video generation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Video generation providers — pluggable backends for video generation. | — |
| _image_utils.py | Internal | Shared image encoding utilities for video generation providers. | ✅ |
| base.py | Core | Abstract base class and registry for video generation providers. | ✅ |
| google_provider.py | Core | Google Veo video generation provider. | ✅ |
| minimax_provider.py | Core | MiniMax (Hailuo Hailuo) video generation provider. | ✅ |
| openai_provider.py | Core | OpenAI Sora video generation provider. | ✅ |
| qwen_provider.py | Core | Qwen (Tongyi Wanxiang) video generation provider. | ✅ |
| registry.py | Core | Global provider registry with lazy initialization of built-in providers. | ✅ |
