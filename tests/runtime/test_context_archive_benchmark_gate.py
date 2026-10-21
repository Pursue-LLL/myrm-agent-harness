from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_benchmark_module() -> ModuleType:
    benchmark_path = Path(__file__).parents[2] / "benchmarks/context_archive_benchmark.py"
    spec = importlib.util.spec_from_file_location("context_archive_benchmark", benchmark_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_context_archive_benchmark_reports_threshold_failures() -> None:
    benchmark = _load_benchmark_module()

    failures = benchmark._threshold_failures(
        [
            {
                "size_bytes": 1024,
                "hash_ms_avg": 2.0,
                "gzip_ms_avg": 1.0,
            }
        ],
        {
            "hash_ms_avg": 1.0,
            "gzip_ms_avg": 1.0,
        },
    )

    assert failures == [
        {
            "size_bytes": 1024,
            "metric": "hash_ms_avg",
            "measured_ms": 2.0,
            "threshold_ms": 1.0,
        }
    ]


def test_context_archive_benchmark_enforces_threshold_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _load_benchmark_module()
    monkeypatch.setattr(benchmark, "_SIZES", (1024,))
    monkeypatch.setattr(benchmark, "_CACHE_PRUNE_SIZE_BYTES", 1024)
    monkeypatch.setattr(benchmark, "_CACHE_PRUNE_STRUCTURED_JSON_SIZE_BYTES", 1024)
    monkeypatch.setattr(benchmark, "_CACHE_PRUNE_UNICODE_SIZE_BYTES", 1024)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "context_archive_benchmark.py",
            "--iterations",
            "1",
            "--enforce-thresholds",
            "--max-hash-ms",
            "0",
            "--max-gzip-ms",
            "0",
            "--max-atomic-write-ms",
            "0",
            "--max-reuse-validation-ms",
            "0",
            "--max-restore-guidance-ms",
            "0",
            "--max-cache-prune-large-payload-ms",
            "0",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        benchmark.main()

    assert exc_info.value.code == 1


def test_context_archive_benchmark_stdout_is_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    benchmark = _load_benchmark_module()
    monkeypatch.setattr(benchmark, "_SIZES", (1024,))
    monkeypatch.setattr(benchmark, "_CACHE_PRUNE_SIZE_BYTES", 1024)
    monkeypatch.setattr(benchmark, "_CACHE_PRUNE_STRUCTURED_JSON_SIZE_BYTES", 1024)
    monkeypatch.setattr(benchmark, "_CACHE_PRUNE_UNICODE_SIZE_BYTES", 1024)
    monkeypatch.setattr(sys, "argv", ["context_archive_benchmark.py", "--iterations", "1"])

    benchmark.main()

    captured = capsys.readouterr()
    assert "[CacheTtlPrune]" not in captured.out
    assert json.loads(captured.out)["threshold_failures"] == []


def test_cache_prune_benchmark_reports_payload_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _load_benchmark_module()
    monkeypatch.setattr(benchmark, "_CACHE_PRUNE_SIZE_BYTES", 1024)
    monkeypatch.setattr(benchmark, "_CACHE_PRUNE_STRUCTURED_JSON_SIZE_BYTES", 1024)
    monkeypatch.setattr(benchmark, "_CACHE_PRUNE_UNICODE_SIZE_BYTES", 1024)

    results = benchmark._bench_cache_prune_large_payload(1)

    assert {result["payload_kind"] for result in results} == {
        "ascii_text_fast_guard",
        "json_structure_trim",
        "json_fast_guard",
        "unicode_text_fast_guard",
    }
    for result in results:
        assert result["kind"] == "cache_ttl_prune_large_payload"
        assert result["cache_prune_large_payload_ms_avg"] >= 0
        sample_estimate = result["sample_estimate"]
        assert sample_estimate["payload_bytes"] == result["size_bytes"]
        assert sample_estimate["estimated_tokens"] > 0
        assert sample_estimate["estimated_content_bytes"] >= sample_estimate["payload_chars"]
