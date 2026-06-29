"""Architecture gate: toolkits/ must not host vendor/product integration packages.

Third-party SaaS wrappers (Google Calendar, Feishu, Notion, etc.) belong in
myrm-agent-server skills, MCP servers, or integrations/ — not harness toolkits/.

See toolkits/_ARCH.md § Hard rules and § Decision flow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[2]
TOOLKITS_ROOT = HARNESS_ROOT / "src" / "myrm_agent_harness" / "toolkits"

# Top-level toolkit package names that indicate a product/vendor integration.
_FORBIDDEN_TOP_LEVEL_TOOLKIT_NAMES: frozenset[str] = frozenset(
    {
        "airtable",
        "asana",
        "bitbucket",
        "confluence",
        "discord",
        "dropbox",
        "feishu",
        "github",
        "gitlab",
        "google",
        "google_calendar",
        "google_workspace",
        "hubspot",
        "huggingface",
        "jira",
        "lark",
        "linear",
        "notion",
        "oauth",
        "salesforce",
        "slack",
        "stripe",
        "telegram",
        "trello",
        "twitter",
        "x",
        "x_twitter",
    }
)

# Prefixes that signal vendor-specific modules when used as toolkit dir or .py stem.
_FORBIDDEN_NAME_PREFIXES: tuple[str, ...] = (
    "feishu_",
    "lark_",
    "google_",
    "slack_",
    "discord_",
    "telegram_",
    "notion_",
    "linear_",
    "github_",
    "gitlab_",
    "huggingface_",
    "hf_",
    "twitter_",
    "salesforce_",
    "hubspot_",
    "jira_",
    "confluence_",
    "dropbox_",
    "stripe_",
    "airtable_",
    "asana_",
    "trello_",
    "bitbucket_",
)

# Runtime/cache paths — not Python packages; skip during top-level scan.
_IGNORED_TOP_LEVEL_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        "local_browser_data",
    }
)

# Generic protocol modules allowed despite matching a forbidden stem/prefix rule.
_ALLOWLISTED_RELATIVE_PATHS: frozenset[str] = frozenset(
    {
        "src/myrm_agent_harness/toolkits/mcp/oauth.py",
    }
)


def _relative_to_harness(path: Path) -> str:
    return str(path.relative_to(HARNESS_ROOT)).replace("\\", "/")


def _is_allowlisted(path: Path) -> bool:
    return _relative_to_harness(path) in _ALLOWLISTED_RELATIVE_PATHS


def _stem_is_vendor_module(stem: str) -> bool:
    lowered = stem.lower()
    if lowered in _FORBIDDEN_TOP_LEVEL_TOOLKIT_NAMES:
        return True
    return any(lowered.startswith(prefix) for prefix in _FORBIDDEN_NAME_PREFIXES)


def _collect_top_level_toolkit_violations() -> list[str]:
    violations: list[str] = []
    for entry in sorted(TOOLKITS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name in _IGNORED_TOP_LEVEL_NAMES or name.startswith("."):
            continue
        if _stem_is_vendor_module(name):
            violations.append(
                f"{_relative_to_harness(entry)}: top-level toolkit package looks like a "
                "vendor integration — use server skills/MCP/integrations/ instead"
            )
    return violations


def _toolkits_relative_depth(path: Path) -> int:
    """Depth from toolkits/ root: ``wiki/foo.py`` → 2; ``llms/a/b/c.py`` → 4."""
    return len(path.relative_to(TOOLKITS_ROOT).parts)


def _collect_vendor_module_violations() -> list[str]:
    """Flag vendor-prefixed modules only at shallow paths (depth ≤ 2).

    Deep paths such as ``llms/video/providers/google_provider.py`` are generic
    multi-provider adapters and are intentionally excluded.
    """
    violations: list[str] = []
    for py_file in sorted(TOOLKITS_ROOT.rglob("*.py")):
        if _is_allowlisted(py_file):
            continue
        if _toolkits_relative_depth(py_file) > 2:
            continue
        stem = py_file.stem
        if stem == "__init__":
            continue
        if not _stem_is_vendor_module(stem):
            continue
        violations.append(
            f"{_relative_to_harness(py_file)}: module stem '{stem}' looks vendor-specific — "
            "belongs in server skills/MCP/integrations/, not toolkits/"
        )
    return violations


@pytest.mark.architecture
def test_toolkits_have_no_vendor_top_level_packages() -> None:
    violations = _collect_top_level_toolkit_violations()
    if violations:
        msg = "toolkits/ vendor top-level package violations:\n" + "\n".join(violations)
        raise AssertionError(msg)


@pytest.mark.architecture
def test_toolkits_have_no_vendor_prefixed_modules() -> None:
    violations = _collect_vendor_module_violations()
    if violations:
        msg = "toolkits/ vendor module name violations:\n" + "\n".join(violations)
        raise AssertionError(msg)


class TestVendorBoundaryDetector:
    """Negative tests for the vendor-name heuristic."""

    def test_detects_google_calendar_package(self) -> None:
        assert _stem_is_vendor_module("google_calendar")

    def test_detects_feishu_prefix(self) -> None:
        assert _stem_is_vendor_module("feishu_webhook")

    def test_allows_generic_wiki_agent_tools(self) -> None:
        assert not _stem_is_vendor_module("wiki_agent_tools")

    def test_allows_generic_mcp_agent_module(self) -> None:
        assert not _stem_is_vendor_module("agent")

    def test_mcp_oauth_is_allowlisted(self) -> None:
        path = TOOLKITS_ROOT / "mcp" / "oauth.py"
        assert _is_allowlisted(path)

    def test_deep_provider_modules_are_excluded_from_shallow_scan(self) -> None:
        deep = TOOLKITS_ROOT / "llms" / "video" / "providers" / "google_provider.py"
        assert deep.is_file()
        assert _toolkits_relative_depth(deep) > 2
        violations = _collect_vendor_module_violations()
        assert not any("google_provider" in v for v in violations)

    def test_x_prefix_does_not_false_positive_xml_utils(self) -> None:
        assert not _stem_is_vendor_module("xml_utils")
