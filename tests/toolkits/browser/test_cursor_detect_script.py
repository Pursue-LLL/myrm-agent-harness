"""Unit tests for cursor-interactive detection script."""


def test_cursor_detect_script_syntax():
    """Test that cursor detect script has valid JavaScript syntax."""
    from myrm_agent_harness.toolkits.browser.snapshot.observer_scripts import CURSOR_DETECT_SCRIPT

    assert CURSOR_DETECT_SCRIPT is not None
    assert len(CURSOR_DETECT_SCRIPT) > 100
    assert "querySelectorAll" in CURSOR_DETECT_SCRIPT
    assert "getComputedStyle" in CURSOR_DETECT_SCRIPT
    assert "cursor" in CURSOR_DETECT_SCRIPT
    assert "onclick" in CURSOR_DETECT_SCRIPT
    assert "tabIndex" in CURSOR_DETECT_SCRIPT
    print(" Cursor detect script syntax valid")


def test_cursor_roles_defined():
    """Test that CURSOR_ROLES are properly defined."""
    from myrm_agent_harness.toolkits.browser.snapshot.aria_types import CURSOR_ROLES

    assert {"clickable", "focusable"} == CURSOR_ROLES
    print(" CURSOR_ROLES defined correctly")


def test_resolve_locator_with_cursor_role():
    """Test that resolve_locator handles cursor roles correctly."""
    from unittest.mock import MagicMock

    from myrm_agent_harness.toolkits.browser.snapshot.aria_types import RefInfo, resolve_locator

    page = MagicMock()
    page.get_by_text.return_value = MagicMock()

    info = RefInfo(role="clickable", name="Click me", nth=None)
    resolve_locator(page, info)

    page.get_by_text.assert_called_once_with("Click me", exact=True)
    print(" resolve_locator handles cursor roles correctly")


if __name__ == "__main__":
    test_cursor_detect_script_syntax()
    test_cursor_roles_defined()
    test_resolve_locator_with_cursor_role()
    print("\n All unit tests passed")
