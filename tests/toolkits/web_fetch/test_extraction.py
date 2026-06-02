"""Anti-bot detector tests — covers Tier 1/2/3, error page detection, and edge cases."""

import pytest

from myrm_agent_harness.toolkits.web_fetch.antibot_detector import is_blocked

# --- Tier 1: High-confidence WAF patterns ---


@pytest.mark.parametrize(
    "html_snippet,expected_reason_fragment",
    [
        ('<form class="challenge-form" action="/__cf_chl_f_tk=abc">', "Cloudflare challenge form"),
        ('<span class="cf-error-code">1020</span>', "Cloudflare firewall block"),
        ('<script src="/cdn-cgi/challenge-platform/scripts/jsd/orchestrate/v1"></script>', "Cloudflare JS challenge"),
        ("window._pxAppId = 'PX123';", "PerimeterX block"),
        ('<iframe src="https://captcha.px-cdn.net/PX123/captcha.js">', "PerimeterX captcha"),
        ('<iframe src="https://geo.captcha-delivery.com/captcha/">', "DataDome captcha"),
        ("<meta name='_Incapsula_Resource'>", "Imperva/Incapsula block"),
        ("Incapsula incident ID: 123456", "Imperva/Incapsula incident"),
        ("Sucuri WebSite Firewall - CloudProxy", "Sucuri firewall block"),
        ("Reference # 18.abc.1234.def", "Akamai block"),
        ("Pardon Our Interruption", "Akamai challenge"),
        ("KPSDK.scriptStart = KPSDK.now()", "Kasada challenge"),
        ("<p>You have been blocked by network security</p>", "Network security block"),
    ],
)
def test_tier1_waf_detection(html_snippet: str, expected_reason_fragment: str):
    blocked, reason = is_blocked(200, html_snippet)
    assert blocked, f"Should detect: {expected_reason_fragment}"
    assert expected_reason_fragment in reason


# --- Tier 2: Medium-confidence on short + error status ---


def _pad_html(body: str) -> str:
    """Pad HTML to exceed near-empty threshold while keeping < Tier2 max size."""
    return f"<html><body>{body}{'<!-- padding -->' * 10}</body></html>"


@pytest.mark.parametrize(
    "body_content,expected_reason_fragment",
    [
        ("<h1>Access Denied</h1><p>You do not have permission to access this resource.</p>", "Access Denied"),
        ("<p>Checking your browser before accessing the site. Please wait a moment.</p>", "Cloudflare browser check"),
        ("<title>Just a moment...</title><p>Please wait while we verify your browser.</p>", "Cloudflare interstitial"),
        (
            '<div class="g-recaptcha" data-sitekey="key"></div><p>Please verify you are human.</p>',
            "reCAPTCHA on block page",
        ),
        (
            '<div class="h-captcha" data-sitekey="key"></div><p>Please verify you are human.</p>',
            "hCaptcha on block page",
        ),
    ],
)
def test_tier2_on_error_status(body_content: str, expected_reason_fragment: str):
    html = _pad_html(body_content)
    blocked, reason = is_blocked(403, html)
    assert blocked, f"Should detect on 403: {expected_reason_fragment}"
    assert expected_reason_fragment in reason


def test_tier1_incapsula_on_403():
    """Incapsula incident is Tier 1 pattern — detected before Tier 2."""
    html = _pad_html("<p>Request unsuccessful. Incapsula incident ID: 123456. Please try again.</p>")
    blocked, reason = is_blocked(403, html)
    assert blocked
    assert "Incapsula" in reason


def test_tier2_not_triggered_on_200_large_page():
    """Tier 2 should NOT fire on 200 + large page with real content."""
    html = (
        "<html><body>"
        "<article><p>Access Denied is sometimes used in fiction.</p></article>"
        + "<p>Real content paragraph. " * 500
        + "</body></html>"
    )
    blocked, _ = is_blocked(200, html)
    assert not blocked


# --- Tier 3: Structural integrity ---


def test_structural_script_heavy_shell():
    html = (
        "<html><body>"
        "<script>window.location='https://evil.com';</script>"
        "<script>var a=1;</script>" + " " * 200 + "</body></html>"
    )
    blocked, reason = is_blocked(200, html)
    assert blocked
    assert "Structural" in reason


def test_structural_ok_with_real_content():
    html = (
        "<html><body>"
        "<article><p>This is a real article with meaningful content that is long enough.</p></article>"
        "<section><p>More real content here for testing purposes to make it longer.</p></section>"
        + "<p>Additional paragraph. " * 20
        + "</body></html>"
    )
    blocked, _ = is_blocked(200, html)
    assert not blocked


# --- Error page detection (requires sufficient HTML so near-empty check doesn't trigger first) ---


def test_error_page_title_404():
    html = (
        "<html><body>"
        "<article><p>This page might have been moved or deleted.</p></article>" + "<p>padding " * 30 + "</body></html>"
    )
    blocked, reason = is_blocked(200, html, title="404 Not Found")
    assert blocked
    assert "Error page title" in reason


def test_error_page_short_content():
    blocked, _reason = is_blocked(200, "page not found", title=None)
    assert blocked


def test_normal_page_not_detected():
    html = (
        "<html><body>"
        "<article><p>Welcome to our site. This is a long article with lots of real content "
        "that should definitely not be flagged as an error page or anti-bot block page.</p></article>"
        + "<p>More content here. " * 30
        + "</body></html>"
    )
    blocked, _ = is_blocked(200, html, title="Welcome to Our Site")
    assert not blocked


# --- HTTP status codes ---


def test_http_429():
    blocked, reason = is_blocked(429, "<html></html>")
    assert blocked
    assert "429" in reason


def test_http_403_empty():
    blocked, reason = is_blocked(403, "")
    assert blocked
    assert "403" in reason


def test_http_503_html_page():
    html = "<html><body><h1>Service Temporarily Unavailable</h1></body></html>"
    blocked, reason = is_blocked(503, html)
    assert blocked
    assert "503" in reason


# --- Edge cases ---


def test_none_html():
    blocked, _ = is_blocked(200, None)
    assert blocked


def test_json_api_response_not_blocked():
    html = '{"data": [1, 2, 3], "status": "ok"}'
    blocked, _ = is_blocked(200, html)
    assert not blocked


def test_xml_response_not_blocked():
    html = '<rss version="2.0"><channel><title>Feed</title></channel></rss>'
    blocked, _ = is_blocked(200, html)
    assert not blocked


def test_large_page_not_structurally_checked():
    html = "<html><body>" + "<article><p>Real content paragraph.</p></article>" * 2000 + "</body></html>"
    blocked, _ = is_blocked(200, html)
    assert not blocked


def test_http_200_near_empty():
    blocked, reason = is_blocked(200, "  ")
    assert blocked
    assert "Near-empty" in reason


def test_http_200_empty_string():
    blocked, reason = is_blocked(200, "")
    assert blocked
    assert "Near-empty" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
