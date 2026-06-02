"""Tests for aria_acquisition (Layer 1) - Fast Path and Custom Path routing."""

import pytest

from myrm_agent_harness.toolkits.browser.snapshot.aria_acquisition import get_aria_tree


class MockPage:
    """Mock Playwright Page for testing."""

    async def evaluate(self, script: str, *args: object) -> list[str]:
        return []


class MockLocator:
    """Mock Playwright Locator for testing."""

    def __init__(self, yaml_output: str | None = None, should_fail: bool = False):
        self.yaml_output = yaml_output or "- button:\n    name: Test"
        self.should_fail = should_fail
        self.evaluate_called = False
        self.aria_snapshot_called = False
        self.page = MockPage()

    async def aria_snapshot(self) -> str:
        """Mock aria_snapshot method."""
        self.aria_snapshot_called = True
        if self.should_fail:
            raise RuntimeError("Mock aria_snapshot failure")
        return self.yaml_output

    async def evaluate(self, script: str, *args: object) -> str:
        """Mock evaluate method."""
        self.evaluate_called = True
        if self.should_fail:
            raise RuntimeError("Mock evaluate failure")
        return "- button:\n    name: Custom"


class TestAriaAcquisition:
    """Test suite for ARIA acquisition layer."""

    @pytest.mark.asyncio
    async def test_fast_path_with_none_depth(self) -> None:
        """Test Fast Path is used when max_depth is None."""
        locator = MockLocator()

        result = await get_aria_tree(locator, max_depth=None)

        assert locator.aria_snapshot_called
        assert not locator.evaluate_called
        assert "button" in result

    @pytest.mark.asyncio
    async def test_custom_path_with_depth(self) -> None:
        """Test Custom Path is used when max_depth is provided."""
        locator = MockLocator()

        result = await get_aria_tree(locator, max_depth=3)

        assert locator.evaluate_called
        assert "button" in result

    @pytest.mark.asyncio
    async def test_fast_path_error_propagation(self) -> None:
        """Test Fast Path propagates errors."""
        locator = MockLocator(should_fail=True)

        with pytest.raises(RuntimeError, match="Mock aria_snapshot failure"):
            await get_aria_tree(locator, max_depth=None)

    @pytest.mark.asyncio
    async def test_custom_path_fallback_to_fast(self) -> None:
        """Test Custom Path falls back to Fast Path on failure."""
        locator = MockLocator()

        # Mock evaluate to fail, but aria_snapshot to succeed
        async def mock_evaluate_fail(*args: object) -> str:
            raise RuntimeError("Custom path failed")

        async def mock_aria_snapshot_succeed() -> str:
            return "- button:\n    name: Fallback"

        locator.evaluate = mock_evaluate_fail  # type: ignore[method-assign]
        locator.aria_snapshot = mock_aria_snapshot_succeed  # type: ignore[method-assign]

        result = await get_aria_tree(locator, max_depth=5)

        assert "Fallback" in result

    @pytest.mark.asyncio
    async def test_custom_path_timeout_fallback(self) -> None:
        """Test Custom Path handles timeout and falls back."""
        import asyncio

        locator = MockLocator()

        # Mock evaluate to hang
        async def mock_evaluate_hang(*args: object) -> str:
            await asyncio.sleep(10)  # Longer than 3s timeout
            return ""

        async def mock_aria_snapshot_succeed() -> str:
            return "- button:\n    name: Timeout Fallback"

        locator.evaluate = mock_evaluate_hang  # type: ignore[method-assign]
        locator.aria_snapshot = mock_aria_snapshot_succeed  # type: ignore[method-assign]

        result = await get_aria_tree(locator, max_depth=3)

        assert "Timeout Fallback" in result

    @pytest.mark.asyncio
    async def test_yaml_output_format(self) -> None:
        """Test YAML output format from Fast Path."""
        yaml_output = """- WebArea:
    name: "Test Page"
    children:
      - button:
          name: "Submit"
"""
        locator = MockLocator(yaml_output=yaml_output)

        result = await get_aria_tree(locator, max_depth=None)

        assert "WebArea" in result
        assert "Test Page" in result
        assert "button" in result

    @pytest.mark.asyncio
    async def test_max_depth_validation_negative(self) -> None:
        """Test that negative max_depth raises ValueError."""
        locator = MockLocator()

        with pytest.raises(ValueError, match="max_depth must be >= 0"):
            await get_aria_tree(locator, max_depth=-1)

    @pytest.mark.asyncio
    async def test_max_depth_validation_non_integer(self) -> None:
        """Test that non-integer max_depth raises ValueError."""
        locator = MockLocator()

        with pytest.raises(ValueError, match="max_depth must be int or None"):
            await get_aria_tree(locator, max_depth=1.5)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_max_depth_large_value_uses_fast_path(self) -> None:
        """Test that large max_depth (>100) automatically uses Fast Path."""
        locator = MockLocator()

        result = await get_aria_tree(locator, max_depth=999)

        # Should use Fast Path (aria_snapshot) instead of Custom Path (evaluate)
        assert locator.aria_snapshot_called
        assert not locator.evaluate_called
        assert "button" in result

    @pytest.mark.asyncio
    async def test_max_depth_zero(self) -> None:
        """Test that max_depth=0 is valid (only root node)."""
        locator = MockLocator()

        # Should not raise error
        result = await get_aria_tree(locator, max_depth=0)

        assert locator.evaluate_called
        assert "Custom" in result
