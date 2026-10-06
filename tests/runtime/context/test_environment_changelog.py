"""Unit tests for dual-readable environment changelog and anti-amnesia recovery ledger."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.environment_changelog import (
    EnvironmentChangelogLedger,
)
from myrm_agent_harness.runtime.context.environment_changelog_types import (
    EnvironmentMutationKind,
    MutationActor,
)


@pytest.fixture
def ledger() -> EnvironmentChangelogLedger:
    return EnvironmentChangelogLedger()


def test_manual_mutation_auditing_and_consolidation(ledger: EnvironmentChangelogLedger) -> None:
    """Validate manual mutation auditing, package upgrade override, and uninstallation."""
    # 1. Install package v1
    ledger.record_mutation(
        kind=EnvironmentMutationKind.PACKAGE_INSTALL,
        target_name="fastapi",
        new_state="0.110.0",
        actor=MutationActor.AGENT,
        rationale="Required for REST gateway",
    )

    # 2. Upgrade to v2
    ledger.record_mutation(
        kind=EnvironmentMutationKind.PACKAGE_INSTALL,
        target_name="fastapi",
        old_state="0.110.0",
        new_state="0.112.0",
        actor=MutationActor.USER,
        rationale="User requested latest router fixes",
    )

    # 3. Mount MCP server
    ledger.record_mutation(
        kind=EnvironmentMutationKind.MCP_TOOL_MOUNT,
        target_name="filesystem-mcp",
        new_state="active",
        actor=MutationActor.AGENT,
    )

    # 4. Set Env Var
    ledger.record_mutation(
        kind=EnvironmentMutationKind.ENV_VAR_CHANGE,
        target_name="API_BASE_URL",
        new_state="https://api.myrm.local",
    )

    digest = ledger.generate_state_digest()
    assert digest.installed_packages == {"fastapi": "0.112.0"}
    assert digest.active_mcp_servers == ["filesystem-mcp"]
    assert digest.effective_env_vars == {"API_BASE_URL": "https://api.myrm.local"}
    assert digest.recent_changes_count == 4

    # 5. Uninstall package
    ledger.record_mutation(
        kind=EnvironmentMutationKind.PACKAGE_INSTALL,
        target_name="fastapi",
        new_state="uninstalled",
        actor=MutationActor.AGENT,
        rationale="Cleanup temporary dependency",
    )
    digest_after_removal = ledger.generate_state_digest()
    assert "fastapi" not in digest_after_removal.installed_packages


def test_bash_execution_heuristic_auto_detection(ledger: EnvironmentChangelogLedger) -> None:
    """Validate automatic heuristic extraction from successful bash commands and stdout."""
    # Python uv pip install
    cmd_uv = "uv pip install pydantic==2.8.2 httpx>=0.27.0"
    stdout_uv = "Resolved 2 packages\nSuccessfully installed pydantic-2.8.2 httpx-0.27.0"
    mutations_py = ledger.parse_bash_execution_for_mutations(cmd_uv, stdout_uv, exit_code=0)

    assert len(mutations_py) == 1
    assert mutations_py[0].kind == EnvironmentMutationKind.PACKAGE_INSTALL
    assert mutations_py[0].target_name == "pydantic"
    assert mutations_py[0].new_state == "2.8.2"

    # Node npm install
    cmd_npm = "npm install lucide-react"
    mutations_node = ledger.parse_bash_execution_for_mutations(cmd_npm, "added 1 package", exit_code=0)
    assert len(mutations_node) == 1
    assert mutations_node[0].target_name == "lucide-react"

    # Env export
    cmd_export = "export MYRM_DEBUG=true && echo 'ready'"
    mutations_env = ledger.parse_bash_execution_for_mutations(cmd_export, "ready", exit_code=0)
    assert len(mutations_env) == 1
    assert mutations_env[0].kind == EnvironmentMutationKind.ENV_VAR_CHANGE
    assert mutations_env[0].target_name == "MYRM_DEBUG"
    assert mutations_env[0].new_state == "true"

    # Failed command should be skipped
    mutations_failed = ledger.parse_bash_execution_for_mutations("npm install broken-pkg", "Error 404", exit_code=1)
    assert len(mutations_failed) == 0


def test_anti_amnesia_context_rehydration_prompt(ledger: EnvironmentChangelogLedger) -> None:
    """Validate generation of prompt payload for cross-session anti-amnesia recovery."""
    ledger.record_mutation(
        kind=EnvironmentMutationKind.PACKAGE_INSTALL,
        target_name="pytest",
        new_state="8.3.1",
        actor=MutationActor.AGENT,
        rationale="Unit test harness",
    )
    ledger.record_mutation(
        kind=EnvironmentMutationKind.MCP_TOOL_MOUNT,
        target_name="postgres-mcp",
        new_state="mounted",
    )

    payload = ledger.render_anti_amnesia_prompt()

    assert "<environment_state_digest>" in payload.prompt_block
    assert "</environment_state_digest>" in payload.prompt_block
    assert "pytest==8.3.1" in payload.prompt_block
    assert "postgres-mcp" in payload.prompt_block
    assert payload.token_count_estimate > 0


def test_dual_readable_jsonl_and_markdown_exports(ledger: EnvironmentChangelogLedger) -> None:
    """Validate machine-readable JSONL round-trip hydration and human-readable Markdown timeline."""
    ledger.record_mutation(
        kind=EnvironmentMutationKind.PACKAGE_INSTALL,
        target_name="requests",
        old_state="2.31.0",
        new_state="2.32.3",
        actor=MutationActor.AGENT,
        rationale="Security CVE patch",
    )

    # 1. Human-readable Markdown
    md_timeline = ledger.export_markdown_timeline()
    assert "### Environment Mutation Timeline" in md_timeline
    assert "[AGENT] (package_install) **requests**:" in md_timeline
    assert "`2.31.0` -> `2.32.3`" in md_timeline
    assert "Security CVE patch" in md_timeline

    # 2. Machine-readable JSONL serialization
    jsonl_str = ledger.export_jsonl()
    assert '"target_name": "requests"' in jsonl_str

    # 3. Hydrate into brand-new ledger
    fresh_ledger = EnvironmentChangelogLedger()
    loaded_count = fresh_ledger.load_jsonl(jsonl_str)
    assert loaded_count == 1

    digest = fresh_ledger.generate_state_digest()
    assert digest.installed_packages == {"requests": "2.32.3"}
