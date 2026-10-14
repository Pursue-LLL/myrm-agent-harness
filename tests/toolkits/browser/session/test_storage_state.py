"""Unit tests for the storage-state helpers that re-inject saved cookies and localStorage."""

from myrm_agent_harness.toolkits.browser.session.storage_state import build_localstorage_script, normalize_cookies


class TestBuildLocalstorageScript:
    """Test build_localstorage_script."""

    def test_without_origin_produces_iife(self) -> None:
        """Test building script without origin guard."""
        items = [{"name": "key1", "value": "value1"}]

        script = build_localstorage_script(items)

        assert script.startswith("(() => {")
        assert "JSON.parse(" in script
        assert "localStorage.setItem" in script
        assert "window.location.origin" not in script

    def test_with_origin_produces_guarded_iife(self) -> None:
        """Test building script with origin guard."""
        items = [{"name": "key1", "value": "val1"}]

        script = build_localstorage_script(items, origin="https://example.com")

        assert "window.location.origin === " in script
        assert '"https://example.com"' in script
        assert "JSON.parse(" in script
        assert "localStorage.setItem" in script

    def test_special_characters_safely_serialised(self) -> None:
        """Test that special characters are safely serialised via JSON."""
        items = [{"name": 'key"with"quotes', "value": "val\\with\\backslash"}]

        script = build_localstorage_script(items, origin="https://evil.com'; alert(1);//")

        assert "alert(1)" not in script or "JSON.parse" in script
        assert "localStorage.setItem" in script

    def test_empty_items_produces_valid_js(self) -> None:
        """Test that empty items list produces valid JS."""
        script = build_localstorage_script([], origin="https://example.com")

        assert "JSON.parse(" in script
        assert script.startswith("(() => {")


class TestNormalizeCookies:
    """Test normalize_cookies function."""

    def test_removes_expires_zero(self) -> None:
        """Session cookies with expires=0 should have expires removed."""
        cookies = [{"name": "sid", "value": "abc", "expires": 0}]
        result = normalize_cookies(cookies)

        assert "expires" not in result[0]
        assert result[0]["name"] == "sid"

    def test_removes_expires_negative(self) -> None:
        """Session cookies with expires=-1 should have expires removed."""
        cookies = [{"name": "sid", "value": "abc", "expires": -1}]
        result = normalize_cookies(cookies)

        assert "expires" not in result[0]

    def test_removes_expires_negative_float(self) -> None:
        """Session cookies with expires=-1.0 should have expires removed."""
        cookies = [{"name": "sid", "value": "abc", "expires": -1.0}]
        result = normalize_cookies(cookies)

        assert "expires" not in result[0]

    def test_preserves_valid_expires(self) -> None:
        """Persistent cookies with valid expires should be preserved."""
        cookies = [{"name": "sid", "value": "abc", "expires": 1722700000}]
        result = normalize_cookies(cookies)

        assert result[0]["expires"] == 1722700000

    def test_normalises_samesite_lowercase(self) -> None:
        """sameSite should be normalized to Title Case."""
        cookies = [
            {"name": "a", "value": "1", "sameSite": "none"},
            {"name": "b", "value": "2", "sameSite": "lax"},
            {"name": "c", "value": "3", "sameSite": "strict"},
        ]
        result = normalize_cookies(cookies)

        assert result[0]["sameSite"] == "None"
        assert result[1]["sameSite"] == "Lax"
        assert result[2]["sameSite"] == "Strict"

    def test_preserves_already_correct_samesite(self) -> None:
        """Already correct sameSite should be preserved."""
        cookies = [{"name": "a", "value": "1", "sameSite": "Lax"}]
        result = normalize_cookies(cookies)

        assert result[0]["sameSite"] == "Lax"

    def test_does_not_modify_original(self) -> None:
        """normalize_cookies should not modify the original list."""
        original = [{"name": "sid", "value": "abc", "expires": 0, "sameSite": "none"}]
        normalize_cookies(original)

        assert original[0]["expires"] == 0
        assert original[0]["sameSite"] == "none"

    def test_empty_list(self) -> None:
        """Empty list should return empty list."""
        assert normalize_cookies([]) == []

    def test_cookie_without_expires_or_samesite(self) -> None:
        """Cookies without expires or sameSite should pass through unchanged."""
        cookies = [{"name": "sid", "value": "abc", "domain": ".example.com"}]
        result = normalize_cookies(cookies)

        assert result[0] == {"name": "sid", "value": "abc", "domain": ".example.com"}
