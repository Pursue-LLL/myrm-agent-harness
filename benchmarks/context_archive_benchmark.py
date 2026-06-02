"""Benchmark core costs of context archive storage.

Measures hash, gzip, atomic write, metadata reuse validation, and restore sidecar
lookup for 10KB, 100KB, and 1MB payloads. Output is JSON for easy regression
tracking in CI or local diagnostics.

[INPUT]
- agent.context_management.tracking.archive_restore::build_archive_restore_guidance (POS: Archive restore DTO layer.)
- infra.atomic_write::atomic_write (POS: Atomic file write with crash-consistency guarantee.)
- runtime.context.restore_map_contract::build_restore_map_json (POS: shared restore-map schema builder)

[OUTPUT]
- main: CLI entrypoint that prints JSON benchmark measurements and optional threshold failures.

[POS]
Context archive benchmark probe. Measures storage and restore guidance costs without creating persistent artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from hashlib import sha256
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import CacheTtlPruneConfig
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor import (
    CacheTtlPruneProcessor,
)
from myrm_agent_harness.agent.context_management.tracking.archive_restore import build_archive_restore_guidance
from myrm_agent_harness.infra.atomic_write import atomic_write
from myrm_agent_harness.runtime.context.restore_map_contract import build_restore_map_json

_SIZES: tuple[int, ...] = (10 * 1024, 100 * 1024, 1024 * 1024)
_CACHE_PRUNE_SIZE_BYTES = 1024 * 1024
_CACHE_PRUNE_STRUCTURED_JSON_SIZE_BYTES = 100 * 1024
_CACHE_PRUNE_UNICODE_SIZE_BYTES = 512 * 1024
_CACHE_PRUNE_FAST_GUARD_CHARS = 100
_CACHE_PRUNE_LOGGER_NAME = "myrm_agent_harness.agent.context_management.pipeline.processors.cache_ttl_prune_processor"
_DEFAULT_ITERATIONS = 5
_DEFAULT_THRESHOLDS_MS: dict[str, float] = {
    "hash_ms_avg": 25.0,
    "gzip_ms_avg": 250.0,
    "atomic_write_ms_avg": 250.0,
    "reuse_validation_ms_avg": 100.0,
    "restore_guidance_ms_avg": 25.0,
    "cache_prune_large_payload_ms_avg": 250.0,
}


class _CachePrunePayloadCase:
    __slots__ = ("fast_guard_chars", "payload", "payload_kind")

    def __init__(self, payload_kind: str, payload: str, fast_guard_chars: int) -> None:
        self.payload_kind = payload_kind
        self.payload = payload
        self.fast_guard_chars = fast_guard_chars


def _payload(size_bytes: int) -> bytes:
    line = b"info: deterministic context archive benchmark payload\n"
    marker = b"ERROR: restore map should point near this failure line\n"
    repeated = line * (size_bytes // len(line) + 1)
    middle = len(repeated) // 2
    data = repeated[:middle] + marker + repeated[middle:]
    return data[:size_bytes]


def _json_payload(size_bytes: int) -> str:
    item = '{"kind":"row","value":"' + ("x" * 128) + '"}'
    item_count = max(1, size_bytes // (len(item) + 1))
    return '{"items":[' + ",".join([item] * item_count) + "]}"


def _unicode_payload(size_bytes: int) -> str:
    line = f"{chr(0x4E2D)} unicode context archive benchmark payload\n"
    encoded_line_size = len(line.encode("utf-8"))
    return (line * (size_bytes // encoded_line_size + 1))[: size_bytes // 2]


def _elapsed_ms(fn: Callable[[], object]) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


@contextmanager
def _suppress_cache_prune_logs() -> Iterator[None]:
    logger = logging.getLogger(_CACHE_PRUNE_LOGGER_NAME)
    previous_disabled = logger.disabled
    logger.disabled = True
    try:
        yield
    finally:
        logger.disabled = previous_disabled


def _restore_map(path: Path, payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    return build_restore_map_json(str(path), text) or ""


def _bench_size(size_bytes: int, iterations: int) -> dict[str, object]:
    payload = _payload(size_bytes)
    payload_hash = sha256(payload).hexdigest()
    compressed = gzip.compress(payload, compresslevel=6)

    hash_times: list[float] = []
    gzip_times: list[float] = []
    write_times: list[float] = []
    reuse_times: list[float] = []
    restore_times: list[float] = []

    with tempfile.TemporaryDirectory(prefix="context-archive-bench-") as tmp_dir:
        archive_path = Path(tmp_dir) / f"archive_{size_bytes}.txt.gz"
        metadata_path = Path(f"{archive_path}.meta.json")
        restore_path = Path(f"{archive_path}.restore.json")
        metadata = json.dumps(
            {
                "schema_version": 1,
                "content_sha256": payload_hash,
                "original_bytes": len(payload),
                "stored_bytes": len(compressed),
                "stored_sha256": sha256(compressed).hexdigest(),
                "compressed": True,
            },
            sort_keys=True,
        )
        restore_map = _restore_map(archive_path, payload)

        for _ in range(iterations):
            hash_times.append(_elapsed_ms(lambda: sha256(payload).hexdigest()))
            gzip_times.append(_elapsed_ms(lambda: gzip.compress(payload, compresslevel=6)))
            write_times.append(
                _elapsed_ms(
                    lambda: (
                        atomic_write(archive_path, compressed),
                        atomic_write(metadata_path, metadata),
                        atomic_write(restore_path, restore_map),
                    )
                )
            )
            reuse_times.append(
                _elapsed_ms(
                    lambda: (
                        json.loads(metadata_path.read_text(encoding="utf-8")),
                        sha256(archive_path.read_bytes()).hexdigest(),
                    )
                )
            )
            restore_times.append(
                _elapsed_ms(lambda: build_archive_restore_guidance(str(archive_path), reason="benchmark"))
            )

    return {
        "size_bytes": size_bytes,
        "iterations": iterations,
        "stored_bytes": len(compressed),
        "hash_ms_avg": _avg(hash_times),
        "gzip_ms_avg": _avg(gzip_times),
        "atomic_write_ms_avg": _avg(write_times),
        "reuse_validation_ms_avg": _avg(reuse_times),
        "restore_guidance_ms_avg": _avg(restore_times),
    }


def _cache_prune_payload_cases() -> tuple[_CachePrunePayloadCase, ...]:
    return (
        _CachePrunePayloadCase(
            payload_kind="ascii_text_fast_guard",
            payload=_payload(_CACHE_PRUNE_SIZE_BYTES).decode("utf-8", errors="replace"),
            fast_guard_chars=_CACHE_PRUNE_FAST_GUARD_CHARS,
        ),
        _CachePrunePayloadCase(
            payload_kind="json_structure_trim",
            payload=_json_payload(_CACHE_PRUNE_STRUCTURED_JSON_SIZE_BYTES),
            fast_guard_chars=max(_CACHE_PRUNE_STRUCTURED_JSON_SIZE_BYTES * 2, 1),
        ),
        _CachePrunePayloadCase(
            payload_kind="json_fast_guard",
            payload=_json_payload(_CACHE_PRUNE_SIZE_BYTES),
            fast_guard_chars=_CACHE_PRUNE_FAST_GUARD_CHARS,
        ),
        _CachePrunePayloadCase(
            payload_kind="unicode_text_fast_guard",
            payload=_unicode_payload(_CACHE_PRUNE_UNICODE_SIZE_BYTES),
            fast_guard_chars=_CACHE_PRUNE_FAST_GUARD_CHARS,
        ),
    )


def _sample_cache_prune_estimate(payload: str, fast_guard_chars: int) -> dict[str, int]:
    config = CacheTtlPruneConfig(large_payload_fast_guard_chars=fast_guard_chars)
    processor = CacheTtlPruneProcessor(config=config, max_context_tokens=128_000)
    return {
        "payload_chars": len(payload),
        "payload_bytes": len(payload.encode("utf-8")),
        "large_payload_fast_guard_chars": fast_guard_chars,
        "estimated_tokens": processor._estimate_content_tokens_for_pruning(payload),
        "estimated_content_bytes": processor._estimate_content_bytes_for_budget(payload),
    }


async def _run_cache_prune_once(payload: str, fast_guard_chars: int) -> None:
    config = CacheTtlPruneConfig(
        soft_trim_ratio=0.01,
        hard_clear_ratio=9.0,
        min_prunable_tokens=1,
        soft_trim_head_chars=256,
        soft_trim_tail_chars=256,
        keep_last_assistant_turns=0,
        large_payload_fast_guard_chars=fast_guard_chars,
    )
    processor = CacheTtlPruneProcessor(config=config, max_context_tokens=128_000)
    context = ProcessorContext(
        messages=[
            HumanMessage(content="benchmark cache prune"),
            ToolMessage(content=payload, tool_call_id="bench_tool_call", name="benchmark_tool"),
        ],
        user_query="benchmark",
        chat_id="context_archive_benchmark",
        metadata={},
        merged_context={},
    )
    await processor.process(context)


def _run_cache_prune_sync(payload: str, fast_guard_chars: int) -> None:
    asyncio.run(_run_cache_prune_once(payload, fast_guard_chars))


def _bench_cache_prune_large_payload(iterations: int) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with _suppress_cache_prune_logs():
        _run_cache_prune_sync("warmup payload " * 1000, _CACHE_PRUNE_FAST_GUARD_CHARS)
        for payload_case in _cache_prune_payload_cases():
            run_case = partial(_run_cache_prune_sync, payload_case.payload, payload_case.fast_guard_chars)
            timings = [_elapsed_ms(run_case) for _ in range(iterations)]
            sample_estimate = _sample_cache_prune_estimate(payload_case.payload, payload_case.fast_guard_chars)
            results.append(
                {
                    "kind": "cache_ttl_prune_large_payload",
                    "payload_kind": payload_case.payload_kind,
                    "size_bytes": sample_estimate["payload_bytes"],
                    "iterations": iterations,
                    "cache_prune_large_payload_ms_avg": _avg(timings),
                    "sample_estimate": sample_estimate,
                }
            )
    return results


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _threshold_failures(
    results: list[dict[str, object]],
    thresholds: dict[str, float],
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for result in results:
        size_bytes = result.get("size_bytes")
        for metric, threshold in thresholds.items():
            measured = result.get(metric)
            if not isinstance(measured, (int, float)):
                continue
            if measured <= threshold:
                continue
            failures.append(
                {
                    "size_bytes": size_bytes,
                    "metric": metric,
                    "measured_ms": measured,
                    "threshold_ms": threshold,
                }
            )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=_DEFAULT_ITERATIONS)
    parser.add_argument("--enforce-thresholds", action="store_true")
    parser.add_argument("--max-hash-ms", type=float, default=_DEFAULT_THRESHOLDS_MS["hash_ms_avg"])
    parser.add_argument("--max-gzip-ms", type=float, default=_DEFAULT_THRESHOLDS_MS["gzip_ms_avg"])
    parser.add_argument("--max-atomic-write-ms", type=float, default=_DEFAULT_THRESHOLDS_MS["atomic_write_ms_avg"])
    parser.add_argument(
        "--max-reuse-validation-ms", type=float, default=_DEFAULT_THRESHOLDS_MS["reuse_validation_ms_avg"]
    )
    parser.add_argument(
        "--max-restore-guidance-ms", type=float, default=_DEFAULT_THRESHOLDS_MS["restore_guidance_ms_avg"]
    )
    parser.add_argument(
        "--max-cache-prune-large-payload-ms",
        type=float,
        default=_DEFAULT_THRESHOLDS_MS["cache_prune_large_payload_ms_avg"],
    )
    args = parser.parse_args()
    iterations = max(args.iterations, 1)
    results = [_bench_size(size, iterations) for size in _SIZES]
    results.extend(_bench_cache_prune_large_payload(iterations))
    thresholds = {
        "hash_ms_avg": max(args.max_hash_ms, 0.0),
        "gzip_ms_avg": max(args.max_gzip_ms, 0.0),
        "atomic_write_ms_avg": max(args.max_atomic_write_ms, 0.0),
        "reuse_validation_ms_avg": max(args.max_reuse_validation_ms, 0.0),
        "restore_guidance_ms_avg": max(args.max_restore_guidance_ms, 0.0),
        "cache_prune_large_payload_ms_avg": max(args.max_cache_prune_large_payload_ms, 0.0),
    }
    failures = _threshold_failures(results, thresholds)
    print(
        json.dumps(
            {
                "results": results,
                "thresholds_ms": thresholds,
                "threshold_failures": failures,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.enforce_thresholds and failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
