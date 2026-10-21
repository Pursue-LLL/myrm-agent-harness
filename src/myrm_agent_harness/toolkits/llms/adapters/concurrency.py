"""LLM Concurrency Control

[INPUT]
- (none — standalone module using only stdlib asyncio)

[OUTPUT]
- get_semaphores(): Async function returning (global_semaphore, model_semaphore) tuple

[POS]
Concurrency gate for LLM calls. Manages per-model and global asyncio semaphores
to prevent OOM and HTTP 429 errors. Configured via environment variables.
"""

from __future__ import annotations

import asyncio
import os

_MODEL_SEMAPHORES: dict[str, asyncio.Semaphore | None] = {}
_SEMAPHORE_LOCK = asyncio.Lock()
_GLOBAL_SEMAPHORE: asyncio.Semaphore | None = None
_GLOBAL_SEMAPHORE_INITIALIZED = False


async def get_semaphores(model_name: str) -> tuple[asyncio.Semaphore | None, asyncio.Semaphore | None]:
    """Returns (global_semaphore, model_semaphore) based on env configuration.

    Environment variables:
        LLM_GLOBAL_MAX_CONCURRENCY: Max concurrent LLM calls across all models
        LLM_LOCAL_MAX_CONCURRENCY: Max concurrent calls per model
    """
    global _GLOBAL_SEMAPHORE, _GLOBAL_SEMAPHORE_INITIALIZED
    async with _SEMAPHORE_LOCK:
        if not _GLOBAL_SEMAPHORE_INITIALIZED:
            global_limit_str = os.environ.get("LLM_GLOBAL_MAX_CONCURRENCY")
            if global_limit_str and global_limit_str.isdigit() and int(global_limit_str) > 0:
                _GLOBAL_SEMAPHORE = asyncio.Semaphore(int(global_limit_str))
            _GLOBAL_SEMAPHORE_INITIALIZED = True

        if model_name not in _MODEL_SEMAPHORES:
            limit_str = os.environ.get("LLM_LOCAL_MAX_CONCURRENCY")
            if limit_str and limit_str.isdigit() and int(limit_str) > 0:
                _MODEL_SEMAPHORES[model_name] = asyncio.Semaphore(int(limit_str))
            else:
                _MODEL_SEMAPHORES[model_name] = None

        return _GLOBAL_SEMAPHORE, _MODEL_SEMAPHORES[model_name]
