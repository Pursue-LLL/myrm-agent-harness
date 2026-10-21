"""Reproducible MCP connection benchmark, runnable against any harness source tree.

The workload spawns real stdio MCP servers (the same stub the production
``MCPConnectionManager`` would launch) and measures wall time plus how many
processes were actually spawned:

- ``sequential_distinct``: connect N distinct servers one after another (the call
  pattern of the pre-parallel ``route_mcp_servers`` loop);
- ``gather_distinct``: connect the same N servers with ``asyncio.gather`` (the
  current routing pattern);
- ``gather_identical``: N concurrent callers asking for the *same* server.

``--osv-lookups`` additionally times repeated OSV malware lookups (live network).

Usage (from the harness root)::

    .venv/bin/python -m tests.performance.mcp_connect_bench
    # Baseline: benchmark a read-only export of HEAD with the very same workload.
    git archive HEAD src | tar -x -C /tmp/mcp_bench_head
    .venv/bin/python -m tests.performance.mcp_connect_bench --src /tmp/mcp_bench_head/src
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import os
import statistics
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.mcp.config import MCPConfig
    from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager

# The stub appends its name to a spawn log *before* importing the MCP SDK, so the log counts launches exactly.
_STUB_SOURCE = """
import sys

spawn_log, name = sys.argv[1], sys.argv[2]
with open(spawn_log, "a", encoding="utf-8") as handle:
    handle.write(name + "\\n")

from mcp.server.mcpserver import MCPServer

server = MCPServer(name)


@server.tool()
def ping() -> str:
    return "pong"


server.run(transport="stdio")
"""

_OSV_ARGS = ["-y", "@modelcontextprotocol/server-everything"]

Strategy = Callable[["MCPConnectionManager", "Sequence[MCPConfig]"], Awaitable[None]]


async def sequential_distinct(manager: MCPConnectionManager, configs: Sequence[MCPConfig]) -> None:
    for cfg in configs:
        await manager.get_connection([cfg])


async def gather_distinct(manager: MCPConnectionManager, configs: Sequence[MCPConfig]) -> None:
    await asyncio.gather(*(manager.get_connection([cfg]) for cfg in configs))


async def gather_identical(manager: MCPConnectionManager, configs: Sequence[MCPConfig]) -> None:
    await asyncio.gather(*(manager.get_connection([configs[0]]) for _ in configs))


STRATEGIES: dict[str, Strategy] = {
    "sequential_distinct": sequential_distinct,
    "gather_distinct": gather_distinct,
    "gather_identical": gather_identical,
}


def build_configs(workdir: Path, servers: int, spawn_log: Path) -> list[MCPConfig]:
    """N distinct stdio server configs backed by the same real stub script."""
    from myrm_agent_harness.toolkits.mcp.config import MCPConfig

    stub = workdir / "bench_stub_server.py"
    stub.write_text(_STUB_SOURCE, encoding="utf-8")
    return [
        MCPConfig(
            name=f"bench{index}",
            type="stdio",
            command=sys.executable,
            args=[str(stub), str(spawn_log), f"bench{index}"],
            description="benchmark stub",
            connect_timeout=120.0,
        )
        for index in range(servers)
    ]


async def run_strategy(strategy: Strategy, workdir: Path, servers: int) -> tuple[float, int]:
    """Run *strategy* on a fresh connection pool; return (seconds, spawned processes)."""
    from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager

    spawn_log = Path(tempfile.mkstemp(dir=workdir, suffix=".spawns")[1])
    configs = build_configs(workdir, servers, spawn_log)
    MCPConnectionManager._instance = None
    manager = await MCPConnectionManager.get_instance()
    try:
        started = time.perf_counter()
        await strategy(manager, configs)
        elapsed = time.perf_counter() - started
    finally:
        await manager.stop()
        MCPConnectionManager._instance = None
    spawns = len([line for line in spawn_log.read_text(encoding="utf-8").splitlines() if line])
    return elapsed, spawns


def supports_osv_cache() -> bool:
    """Whether this source tree's ``check_osv_malware`` can serve repeat lookups from memory."""
    from myrm_agent_harness.toolkits.mcp import security

    return "use_cache" in inspect.signature(security.check_osv_malware).parameters


async def run_osv(lookups: int, *, cached: bool) -> tuple[float, int]:
    """Time *lookups* sequential OSV checks; return (seconds, HTTP clients actually opened)."""
    from myrm_agent_harness.toolkits.mcp import security

    clear = getattr(security, "clear_osv_malware_cache", None)
    if clear is not None:
        clear()
    requests = 0
    real_factory = security.create_httpx_client

    def counting_factory(**kwargs: float) -> object:
        nonlocal requests
        requests += 1
        return real_factory(**kwargs)

    security.create_httpx_client = counting_factory
    try:
        started = time.perf_counter()
        for _ in range(lookups):
            if supports_osv_cache():
                await security.check_osv_malware("npx", _OSV_ARGS, use_cache=cached)
            else:
                await security.check_osv_malware("npx", _OSV_ARGS)
        return time.perf_counter() - started, requests
    finally:
        security.create_httpx_client = real_factory


def _summary(values: Sequence[float]) -> str:
    return f"min={min(values):7.2f}s  median={statistics.median(values):7.2f}s  all={[round(v, 2) for v in values]}"


async def _report_stdio(args: argparse.Namespace) -> None:
    with tempfile.TemporaryDirectory(prefix="mcp_bench_") as tmp:
        workdir = Path(tmp)
        for name, strategy in STRATEGIES.items():
            runs = [await run_strategy(strategy, workdir, args.servers) for _ in range(args.rounds)]
            seconds = [elapsed for elapsed, _ in runs]
            print(f"{name:20s} {_summary(seconds)}  spawns={[spawned for _, spawned in runs]}")


async def _report_osv(args: argparse.Namespace) -> None:
    print(f"\nOSV: {args.osv_lookups} sequential lookups of one npm package (live network)")
    for label, cached in (("osv_uncached", False), ("osv_cached", True)):
        if cached and not supports_osv_cache():
            print(f"{label:20s} n/a (this source tree has no OSV cache)")
            continue
        runs = [await run_osv(args.osv_lookups, cached=cached) for _ in range(args.rounds)]
        print(f"{label:20s} {_summary([elapsed for elapsed, _ in runs])}  http_clients={[count for _, count in runs]}")


async def _main(args: argparse.Namespace) -> None:
    import myrm_agent_harness

    print(f"harness source : {Path(myrm_agent_harness.__file__).parent}")
    print(f"python         : {sys.version.split()[0]}   cpu_count={os.cpu_count()}   loadavg={os.getloadavg()}")
    print(f"workload       : {args.servers} real stdio servers x {args.rounds} rounds\n")
    await _report_stdio(args)
    if args.osv_lookups:
        await _report_osv(args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, help="harness `src` directory to benchmark instead of the working tree")
    parser.add_argument("--servers", type=int, default=6)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--osv-lookups", type=int, default=0, help="also time N repeated OSV lookups (needs network)")
    args = parser.parse_args()
    if args.src is not None:
        sys.path.insert(0, str(args.src.resolve()))
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
