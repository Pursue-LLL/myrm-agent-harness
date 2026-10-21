"""Read concurrency semaphore registry.

[INPUT]
- asyncio::Semaphore (POS: asyncio 并发控制)
- agent.config::FileIOConfig (POS: 文件 I/O 限制配置)

[OUTPUT]
- get_read_semaphore: event-loop scoped read semaphore lookup.

[POS]
File read concurrency guard. Keeps read semaphores scoped to the active event loop to avoid cross-loop semaphore reuse.
"""

import asyncio

from myrm_agent_harness.agent.config import FileIOConfig

_read_semaphores: dict[int, asyncio.Semaphore] = {}


async def get_read_semaphore(io_config: FileIOConfig) -> asyncio.Semaphore:
    """Get or create read semaphore for current event loop."""
    try:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
    except RuntimeError:
        return asyncio.Semaphore(io_config.max_concurrent_reads)

    if loop_id not in _read_semaphores:
        _read_semaphores[loop_id] = asyncio.Semaphore(io_config.max_concurrent_reads)

    return _read_semaphores[loop_id]


__all__ = ["get_read_semaphore"]
