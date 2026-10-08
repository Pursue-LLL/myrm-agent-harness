"""Unit tests for Scoped CSS Isolation and Parallel Micro-Agent Boundary Sentinel Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.scoped_css_sentinel import (
    ConcurrentStyleConflictDetector,
    ConcurrentStylePatch,
    CssViolationSeverity,
    ScopedCssAstRewriter,
)


def test_scoped_css_rewriter_standard_rules() -> None:
    """Verify standard selector scoping and prefix normalization."""
    rewriter = ScopedCssAstRewriter()
    css = """
    .btn {
        background-color: blue;
        color: white;
    }
    .header, .title {
        font-size: 1.5rem;
    }
    """
    res = rewriter.scope_css(css, "drawer-dialog")
    assert res.is_valid is True
    assert res.scope_id == "#drawer-dialog"
    assert res.rules_rewritten == 2
    assert "#drawer-dialog .btn" in res.scoped_css
    assert "#drawer-dialog .header, #drawer-dialog .title" in res.scoped_css


def test_scoped_css_rewriter_rejects_global_selectors() -> None:
    """Verify static rejection of unconfined global root selectors."""
    rewriter = ScopedCssAstRewriter()
    malicious_css = """
    body {
        background-color: #000;
    }
    :root {
        --primary: #ff0000;
    }
    * {
        box-sizing: border-box;
    }
    """
    res = rewriter.scope_css(malicious_css, ".component-modal")
    assert res.is_valid is False
    assert len(res.violations) == 3
    assert all(v.severity == CssViolationSeverity.CRITICAL_REJECTION for v in res.violations)
    assert res.scoped_css == ""


def test_scoped_css_media_query_support() -> None:
    """Verify recursive selector scoping inside @media query containers."""
    rewriter = ScopedCssAstRewriter()
    media_css = """
    @media (max-width: 600px) {
        .panel {
            display: none;
        }
    }
    """
    res = rewriter.scope_css(media_css, "#sidebar")
    assert res.is_valid is True
    assert "@media (max-width: 600px)" in res.scoped_css
    assert "#sidebar .panel" in res.scoped_css


def test_conflict_detector_orthogonal_merge() -> None:
    """Verify two concurrent agents modifying distinct components merge cleanly."""
    detector = ConcurrentStyleConflictDetector()
    patch_a = ConcurrentStylePatch(
        agent_id="drawer_agent",
        component_target_id="drawer-dialog",
        css_content=".close-btn { opacity: 0.8; }",
    )
    patch_b = ConcurrentStylePatch(
        agent_id="banner_agent",
        component_target_id="promo-banner",
        css_content=".headline { font-weight: bold; }",
    )

    res = detector.check_and_merge_patches([patch_a, patch_b])
    assert res.has_conflict is False
    assert res.conflicting_agents == []
    assert res.merged_scoped_css is not None
    assert "#drawer-dialog .close-btn" in res.merged_scoped_css
    assert "#promo-banner .headline" in res.merged_scoped_css


def test_conflict_detector_target_collision() -> None:
    """Verify simultaneous conflicting modifications to the same component are blocked."""
    detector = ConcurrentStyleConflictDetector()
    patch_1 = ConcurrentStylePatch(
        agent_id="agent_alpha",
        component_target_id="action-bar",
        css_content=".btn { background: red; }",
    )
    patch_2 = ConcurrentStylePatch(
        agent_id="agent_beta",
        component_target_id="action-bar",
        css_content=".btn { background: green; }",
    )

    res = detector.check_and_merge_patches([patch_1, patch_2])
    assert res.has_conflict is True
    assert set(res.conflicting_agents) == {"agent_alpha", "agent_beta"}
    assert "collision detected" in res.reason
    assert res.merged_scoped_css is None


def test_conflict_detector_catches_agent_global_pollution() -> None:
    """Verify an agent attempting global root pollution invalidates the batch."""
    detector = ConcurrentStyleConflictDetector()
    patch_ok = ConcurrentStylePatch(
        agent_id="safe_agent",
        component_target_id="card-list",
        css_content=".card { padding: 1rem; }",
    )
    patch_polluter = ConcurrentStylePatch(
        agent_id="polluting_agent",
        component_target_id="footer",
        css_content="body { margin: 0; }",
    )

    res = detector.check_and_merge_patches([patch_ok, patch_polluter])
    assert res.has_conflict is True
    assert res.conflicting_agents == ["polluting_agent"]
    assert "prohibited styles" in res.reason
