"""Integration tests for KNOWN_ISSUES and ADR living docs scanning."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.agent.workspace_rules.scanner import scan_workspace_rules


class TestKnownIssuesIntegration:
    def test_known_issues_coexists_with_agents_md(self, tmp_path: Path) -> None:
        """Ensure KNOWN_ISSUES.md does not get dropped by AGENTS.md First-Match-Wins."""
        (tmp_path / ".git").mkdir()
        (tmp_path / "AGENTS.md").write_text("# Main Persona\nYou are an AI assistant.")
        (tmp_path / "KNOWN_ISSUES.md").write_text(
            "# Known Issues\n\n### [KI-001] OpenSSL Build Issue\nWorkaround: add OPENSSL_DIR."
        )

        rules = scan_workspace_rules(str(tmp_path))
        sources = [r.source for r in rules]

        assert "AGENTS.md" in sources
        assert "KNOWN_ISSUES.md" in sources
        assert len(rules) == 2

    def test_known_issues_with_accepted_adrs(self, tmp_path: Path) -> None:
        """Ensure AGENTS.md, KNOWN_ISSUES.md, and docs/decisions/*.md all coexist."""
        (tmp_path / ".git").mkdir()
        (tmp_path / "AGENTS.md").write_text("# Persona\nCode strictly in Python.")
        (tmp_path / "KNOWN_ISSUES.md").write_text("# Pitfalls\nAvoid legacy pip.")

        decisions_dir = tmp_path / "docs" / "decisions"
        decisions_dir.mkdir(parents=True)
        (decisions_dir / "0001-use-uv.md").write_text(
            "# 0001: Use UV\n* Status: accepted\n\nFast packaging."
        )
        (decisions_dir / "0002-use-pipenv.md").write_text(
            "# 0002: Use Pipenv\n* Status: deprecated\n\nSlow."
        )

        rules = scan_workspace_rules(str(tmp_path))
        sources = [r.source for r in rules]

        assert "AGENTS.md" in sources
        assert "KNOWN_ISSUES.md" in sources
        assert "docs/decisions/0001-use-uv.md" in sources
        assert "docs/decisions/0002-use-pipenv.md" not in sources
        assert len(rules) == 3

    def test_lowercase_known_issues_md(self, tmp_path: Path) -> None:
        """Support lowercase known_issues.md."""
        (tmp_path / ".git").mkdir()
        (tmp_path / "known_issues.md").write_text("# Known issues\nQuirk details.")

        rules = scan_workspace_rules(str(tmp_path))
        sources_lower = [r.source.lower() for r in rules]

        assert "known_issues.md" in sources_lower
        assert any("Quirk details" in r.content for r in rules)
