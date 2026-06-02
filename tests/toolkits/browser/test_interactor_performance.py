"""Performance comparison test for Interactor optimization."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.xdist_group("browser_perf")

from myrm_agent_harness.toolkits.browser.session import Interactor
from myrm_agent_harness.toolkits.browser.snapshot import RefInfo


@pytest.fixture
def mock_page() -> MagicMock:
    """Create mock Page."""
    page = MagicMock()
    page.evaluate = AsyncMock()
    return page


@pytest.fixture
def sample_refs() -> dict[str, RefInfo]:
    """Create sample refs."""
    return {
        "e0": RefInfo(role="button", name="Submit", nth=0),
        "e1": RefInfo(role="textbox", name="Email", nth=0),
        "e2": RefInfo(role="checkbox", name="Subscribe", nth=0),
    }


@pytest.fixture
def interactor(mock_page: MagicMock, sample_refs: dict[str, RefInfo]) -> Interactor:
    """Create Interactor instance."""
    return Interactor(mock_page, sample_refs)


@pytest.mark.asyncio
async def test_performance_simple_actions(interactor: Interactor) -> None:
    """Test performance of simple actions (click/fill/check)."""
    mock_locator = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.fill = AsyncMock()
    mock_locator.check = AsyncMock()
    mock_locator.get_attribute.return_value = "text"

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        # Warm up
        await interactor.interact("click", "e0")

        # Benchmark: 1000 iterations
        iterations = 1000
        start = time.perf_counter()

        for _ in range(iterations):
            await interactor.interact("click", "e0")
            await interactor.interact("fill", "e1", "test@example.com")
            await interactor.interact("check", "e2")

        elapsed = time.perf_counter() - start
        avg_per_call = elapsed / (iterations * 3) * 1000  # ms

        print(f"\n{'=' * 60}")
        print("Performance Test Results:")
        print(f"{'=' * 60}")
        print(f"Total iterations: {iterations * 3:,} calls")
        print(f"Total time: {elapsed:.3f}s")
        print(f"Average per call: {avg_per_call:.4f}ms")
        print(f"Throughput: {(iterations * 3) / elapsed:.0f} calls/sec")
        print(f"{'=' * 60}")

        # Assert performance target (1ms is reasonable for mock operations)
        assert avg_per_call < 1.0, f"Performance regression: {avg_per_call:.4f}ms > 1.0ms"


@pytest.mark.asyncio
async def test_performance_special_actions(interactor: Interactor) -> None:
    """Test performance of special actions (scroll/drag)."""
    mock_locator = AsyncMock()
    mock_locator.scroll_into_view_if_needed = AsyncMock()
    mock_locator.drag_to = AsyncMock()
    mock_locator.get_attribute.return_value = "text"

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        # Benchmark: 500 iterations
        iterations = 500
        start = time.perf_counter()

        for _ in range(iterations):
            await interactor.interact("scroll", "e0", "100")
            await interactor.interact("drag", "e0", "200,150")

        elapsed = time.perf_counter() - start
        avg_per_call = elapsed / (iterations * 2) * 1000  # ms

        print(f"\n{'=' * 60}")
        print("Special Actions Performance:")
        print(f"{'=' * 60}")
        print(f"Total iterations: {iterations * 2:,} calls")
        print(f"Total time: {elapsed:.3f}s")
        print(f"Average per call: {avg_per_call:.4f}ms")
        print(f"{'=' * 60}")

        assert avg_per_call < 1.0, f"Performance regression: {avg_per_call:.4f}ms > 1.0ms"


@pytest.mark.asyncio
async def test_memory_efficiency(interactor: Interactor) -> None:
    """Test memory efficiency (no function object overhead)."""
    import sys

    # Measure Interactor instance size
    instance_size = sys.getsizeof(interactor)
    refs_size = sys.getsizeof(interactor._refs)

    print(f"\n{'=' * 60}")
    print("Memory Efficiency:")
    print(f"{'=' * 60}")
    print(f"Interactor instance: {instance_size} bytes")
    print(f"Refs dict: {refs_size} bytes")
    print(f"Total: {instance_size + refs_size} bytes")
    print(f"{'=' * 60}")

    # Verify no extra function objects
    assert not hasattr(interactor, "_handle_click")
    assert not hasattr(interactor, "_handle_fill")
    assert not hasattr(interactor, "_execute_action")

    print(" No redundant function objects!")


@pytest.mark.asyncio
async def test_concurrent_interactions(interactor: Interactor) -> None:
    """Test concurrent interaction performance."""
    mock_locator = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.fill = AsyncMock()
    mock_locator.check = AsyncMock()
    mock_locator.get_attribute.return_value = "text"

    with patch("myrm_agent_harness.toolkits.browser.session.interactor.resolve_locator", return_value=mock_locator):
        # Simulate Agent performing 10 concurrent interactions
        start = time.perf_counter()

        tasks = [
            interactor.interact("click", "e0"),
            interactor.interact("fill", "e1", "text1"),
            interactor.interact("check", "e2"),
            interactor.interact("click", "e0"),
            interactor.interact("fill", "e1", "text2"),
            interactor.interact("check", "e2"),
            interactor.interact("click", "e0"),
            interactor.interact("fill", "e1", "text3"),
            interactor.interact("check", "e2"),
            interactor.interact("click", "e0"),
        ]

        results = await asyncio.gather(*tasks)

        elapsed = time.perf_counter() - start

        print(f"\n{'=' * 60}")
        print("Concurrent Interaction Test:")
        print(f"{'=' * 60}")
        print(f"Concurrent tasks: {len(tasks)}")
        print(f"Total time: {elapsed:.4f}s")
        print(f"Average per task: {elapsed / len(tasks) * 1000:.4f}ms")
        print(f"{'=' * 60}")

        assert len(results) == len(tasks)
        assert all("e0" in r or "e1" in r or "e2" in r for r in results)
