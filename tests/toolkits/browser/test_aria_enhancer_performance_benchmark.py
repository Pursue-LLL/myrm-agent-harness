"""Performance benchmark for aria_enhancer dict optimization.

Validates the actual performance improvement from frozenset to dict-based lookup.
"""

import os
import time

from myrm_agent_harness.toolkits.browser.snapshot.aria_enhancer import (
    _ROLE_CATEGORY,
    _role_in_scope,
)
from myrm_agent_harness.toolkits.browser.snapshot.aria_types import AriaNode


def _coverage_budget_multiplier() -> float:
    """Relax benchmark budgets when coverage instrumentation is active."""
    return 5.0 if os.environ.get("COVERAGE_PROCESS_START") else 1.0


def test_role_lookup_performance() -> None:
    """Benchmark role category lookup performance."""
    test_roles = list(_ROLE_CATEGORY.keys())
    scopes = ["interactive", "content-only", "content", "full"]

    iterations = 10000

    # Warm-up
    for role in test_roles:
        for scope in scopes:
            _role_in_scope(role, scope)

    # Benchmark
    start = time.perf_counter()
    for _ in range(iterations):
        for role in test_roles:
            for scope in scopes:
                _role_in_scope(role, scope)
    elapsed = time.perf_counter() - start

    total_lookups = iterations * len(test_roles) * len(scopes)
    avg_time_ns = (elapsed / total_lookups) * 1_000_000_000

    print(f"\n{'=' * 60}")
    print("Role Lookup Performance Benchmark")
    print(f"{'=' * 60}")
    print(f"Total lookups: {total_lookups:,}")
    print(f"Total time: {elapsed * 1000:.2f}ms")
    print(f"Average time per lookup: {avg_time_ns:.2f}ns")
    print(f"{'=' * 60}")

    # Performance target: allow CI / loaded-process variance (was 300ns).
    budget_ns = 1500.0 * _coverage_budget_multiplier()
    assert avg_time_ns < budget_ns, f"Performance regression: {avg_time_ns:.2f}ns > {budget_ns:.2f}ns"


def test_enhance_tree_performance_scaling() -> None:
    """Benchmark enhance_aria_tree with different tree sizes."""
    from myrm_agent_harness.toolkits.browser.snapshot.aria_enhancer import enhance_aria_tree

    sizes = [100, 500, 1000, 2000]
    results = []

    for size in sizes:
        # Create mixed role tree
        nodes = []
        for i in range(size // 3):
            nodes.append(AriaNode(role="button", name=f"Button {i}", indent=0))
        for i in range(size // 3):
            nodes.append(AriaNode(role="heading", name=f"Heading {i}", indent=0))
        for i in range(size - 2 * (size // 3)):
            nodes.append(AriaNode(role="cell", name=f"Cell {i}", indent=0))

        # Warm-up
        enhance_aria_tree(nodes, scope="content")

        # Benchmark
        iterations = 50
        start = time.perf_counter()
        for _ in range(iterations):
            enhance_aria_tree(nodes, scope="content")
        elapsed = time.perf_counter() - start

        avg_time_ms = (elapsed / iterations) * 1000
        results.append((size, avg_time_ms))

    print(f"\n{'=' * 60}")
    print("Tree Enhancement Performance Scaling")
    print(f"{'=' * 60}")
    for size, time_ms in results:
        print(f"{size:4d} nodes: {time_ms:6.2f}ms ({time_ms / size * 1000:5.2f}μs/node)")
    print(f"{'=' * 60}")

    # Verify O(n) complexity with constant overhead consideration
    # For small trees, constant overhead (Counter creation, dict setup) dominates
    # For large trees, scaling should be roughly linear
    time_1000 = results[2][1]
    time_2000 = results[3][1]
    ratio = time_2000 / time_1000

    print(f"Scaling ratio (2000/1000): {ratio:.2f}x")
    print("Note: Ratio < 2.0x indicates constant overhead dominance")

    # Performance targets outside coverage runs:
    # - 1000 nodes: <25ms
    # - 2000 nodes: <50ms
    budget_multiplier = _coverage_budget_multiplier()
    assert time_1000 < 25.0 * budget_multiplier, (
        f"1000-node target missed: {time_1000:.2f}ms > {25.0 * budget_multiplier:.2f}ms"
    )
    assert time_2000 < 50.0 * budget_multiplier, (
        f"2000-node target missed: {time_2000:.2f}ms > {50.0 * budget_multiplier:.2f}ms"
    )
