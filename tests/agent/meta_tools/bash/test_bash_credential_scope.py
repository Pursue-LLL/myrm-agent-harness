"""Tests for skill-scoped OAuth credential injection in bash execution."""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.agent.meta_tools.bash.bash_executor import BashExecutor
from myrm_agent_harness.agent.security.types import EphemeralUserCredential, user_credentials_ctx
from myrm_agent_harness.toolkits.code_execution import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor


def test_bash_executor_scopes_issuers_when_skill_detected() -> None:
    mock_executor = MagicMock()
    mock_executor.config = ExecutionConfig()
    bash_executor = BashExecutor(executor=mock_executor)
    bash_executor.set_skill_oauth_issuers({"google-workspace": "google_workspace"})

    assert bash_executor._resolve_allowed_credential_issuers(None) is None
    assert bash_executor._resolve_allowed_credential_issuers([]) is None
    assert bash_executor._resolve_allowed_credential_issuers(["google-workspace"]) == ["google_workspace"]
    assert bash_executor._resolve_allowed_credential_issuers(["unknown-skill"]) == []


def test_local_executor_build_bash_env_scopes_by_allowed_issuers() -> None:
    cred_google = EphemeralUserCredential(issuer="google_workspace", token="gw-token")
    cred_github = EphemeralUserCredential(issuer="github", token="gh-token")
    token = user_credentials_ctx.set((cred_google, cred_github))

    try:
        executor = LocalExecutor(config=ExecutionConfig())
        all_env = executor._build_bash_env(None, allowed_credential_issuers=None)
        assert all_env["GOOGLE_WORKSPACE_TOKEN"] == "gw-token"
        assert all_env["GITHUB_TOKEN"] == "gh-token"

        scoped_env = executor._build_bash_env(None, allowed_credential_issuers=["google_workspace"])
        assert scoped_env["GOOGLE_WORKSPACE_TOKEN"] == "gw-token"
        assert "GITHUB_TOKEN" not in scoped_env

        empty_env = executor._build_bash_env(None, allowed_credential_issuers=[])
        assert "GOOGLE_WORKSPACE_TOKEN" not in empty_env
        assert "GITHUB_TOKEN" not in empty_env
    finally:
        user_credentials_ctx.reset(token)
