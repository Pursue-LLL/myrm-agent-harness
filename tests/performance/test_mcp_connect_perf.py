"""Performance regression guards for MCP connection pooling (real stdio servers).

Measured on 6 real stdio servers (host load ~20), best of rounds: parallel connect is ~4.5x faster
than connecting one by one, while the pre-refactor ``asyncio.gather`` was ~0.8x (a global create
lock serialised every connect). The threshold sits between the two, so the guard fails if
parallelism is lost and does not flap on host load.

Run with ``-m performance``; ``python -m tests.performance.mcp_connect_bench`` prints the full table.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.performance.mcp_connect_bench import STRATEGIES, run_strategy

pytestmark = pytest.mark.performance

_SERVERS = 6
_ROUNDS = 2
_MIN_SPEEDUP = 2.0


async def _best_of(name: str, workdir: Path) -> tuple[float, int]:
    runs = [await run_strategy(STRATEGIES[name], workdir, _SERVERS) for _ in range(_ROUNDS)]
    return min(elapsed for elapsed, _ in runs), runs[0][1]


@pytest.mark.asyncio
async def test_distinct_servers_connect_in_parallel(tmp_path: Path) -> None:
    sequential, sequential_spawns = await _best_of("sequential_distinct", tmp_path)
    parallel, parallel_spawns = await _best_of("gather_distinct", tmp_path)

    assert sequential_spawns == parallel_spawns == _SERVERS
    assert sequential / parallel >= _MIN_SPEEDUP, (
        f"parallel connect lost its edge: sequential={sequential:.2f}s parallel={parallel:.2f}s"
    )


@pytest.mark.asyncio
async def test_identical_concurrent_requests_share_one_spawn(tmp_path: Path) -> None:
    _, spawns = await _best_of("gather_identical", tmp_path)

    assert spawns == 1
