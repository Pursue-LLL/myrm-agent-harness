"""Micro-benchmark for get_all_refs() performance comparison."""

from types import MappingProxyType

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo


def get_all_refs_copy(refs: dict[str, RefInfo]) -> dict[str, RefInfo]:
    """Baseline: return copy."""
    return refs.copy()


def get_all_refs_proxy(refs: dict[str, RefInfo]) -> MappingProxyType[str, RefInfo]:
    """Optimized: return immutable view."""
    return MappingProxyType(refs)


@pytest.fixture
def refs_100() -> dict[str, RefInfo]:
    """100 refs for benchmarking."""
    return {f"e{i}": RefInfo(role="button", name=f"Action {i}", nth=None, bbox=None, position=None) for i in range(100)}


@pytest.fixture
def refs_500() -> dict[str, RefInfo]:
    """500 refs for benchmarking."""
    return {f"e{i}": RefInfo(role="button", name=f"Action {i}", nth=None, bbox=None, position=None) for i in range(500)}


@pytest.fixture
def refs_1000() -> dict[str, RefInfo]:
    """1000 refs for benchmarking."""
    return {
        f"e{i}": RefInfo(role="button", name=f"Action {i}", nth=None, bbox=None, position=None) for i in range(1000)
    }


def test_get_all_refs_copy_100(benchmark, refs_100: dict[str, RefInfo]) -> None:
    """Benchmark: copy() with 100 refs."""
    benchmark.pedantic(
        get_all_refs_copy,
        args=(refs_100,),
        iterations=1000,
        rounds=10,
        warmup_rounds=5,
    )


def test_get_all_refs_proxy_100(benchmark, refs_100: dict[str, RefInfo]) -> None:
    """Benchmark: MappingProxyType with 100 refs."""
    benchmark.pedantic(
        get_all_refs_proxy,
        args=(refs_100,),
        iterations=1000,
        rounds=10,
        warmup_rounds=5,
    )


def test_get_all_refs_copy_500(benchmark, refs_500: dict[str, RefInfo]) -> None:
    """Benchmark: copy() with 500 refs."""
    benchmark.pedantic(
        get_all_refs_copy,
        args=(refs_500,),
        iterations=1000,
        rounds=10,
        warmup_rounds=5,
    )


def test_get_all_refs_proxy_500(benchmark, refs_500: dict[str, RefInfo]) -> None:
    """Benchmark: MappingProxyType with 500 refs."""
    benchmark.pedantic(
        get_all_refs_proxy,
        args=(refs_500,),
        iterations=1000,
        rounds=10,
        warmup_rounds=5,
    )


def test_get_all_refs_copy_1000(benchmark, refs_1000: dict[str, RefInfo]) -> None:
    """Benchmark: copy() with 1000 refs."""
    benchmark.pedantic(
        get_all_refs_copy,
        args=(refs_1000,),
        iterations=1000,
        rounds=10,
        warmup_rounds=5,
    )


def test_get_all_refs_proxy_1000(benchmark, refs_1000: dict[str, RefInfo]) -> None:
    """Benchmark: MappingProxyType with 1000 refs."""
    benchmark.pedantic(
        get_all_refs_proxy,
        args=(refs_1000,),
        iterations=1000,
        rounds=10,
        warmup_rounds=5,
    )
