"""Unit tests for FactPatchRegistry and FactProjectionInterceptor."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.fact_editing.interceptor import (
    FactProjectionInterceptor,
)
from myrm_agent_harness.toolkits.memory.fact_editing.models import FactPatch
from myrm_agent_harness.toolkits.memory.fact_editing.registry import (
    FactPatchRegistry,
)


class TestFactPatchRegistry:
    @pytest.mark.asyncio
    async def test_register_and_automatic_anti_bias_extraction(self) -> None:
        registry = FactPatchRegistry()

        # Inferred anti-bias pattern from natural statement ("from master to main")
        patch = await registry.register_patch(
            entity="default_branch",
            attribute="name",
            override_value="main",
            statement="Change primary git branch from master to main",
        )

        assert patch.entity == "default_branch"
        assert patch.override_value == "main"
        assert patch.is_active is True
        assert "master" in patch.anti_bias_patterns

    @pytest.mark.asyncio
    async def test_idempotent_patch_update(self) -> None:
        registry = FactPatchRegistry()

        p1 = await registry.register_patch(
            entity="database",
            attribute="engine",
            override_value="postgres",
            statement="Use postgres instead of mysql",
        )
        assert p1.override_value == "postgres"
        assert "mysql" in p1.anti_bias_patterns

        # Update with new override value and additional pattern
        p2 = await registry.register_patch(
            entity="database",
            attribute="engine",
            override_value="postgresql_16",
            statement="Upgraded to postgresql_16, strictly never use mariadb",
            anti_bias_patterns=["mariadb"],
        )
        assert p2.patch_id == p1.patch_id
        assert p2.override_value == "postgresql_16"
        # Both mysql (historical) and mariadb (new) should be present
        assert "mysql" in p2.anti_bias_patterns
        assert "mariadb" in p2.anti_bias_patterns

    @pytest.mark.asyncio
    async def test_deactivate_patch(self) -> None:
        registry = FactPatchRegistry()

        patch = await registry.register_patch(
            entity="theme",
            attribute="mode",
            override_value="dark",
            statement="Always dark mode",
        )
        active_before = await registry.get_active_patches()
        assert len(active_before) == 1

        success = await registry.deactivate_patch(patch.patch_id)
        assert success is True

        active_after = await registry.get_active_patches()
        assert len(active_after) == 0

    @pytest.mark.asyncio
    async def test_disk_persistence_and_reload(self, tmp_path: Path) -> None:
        storage_dir = tmp_path / "patch_store"

        reg1 = FactPatchRegistry(storage_dir=storage_dir)
        await reg1.register_patch(
            entity="python_version",
            attribute="target",
            override_value="3.12",
            statement="Require Python 3.12, not 3.10",
        )

        reg2 = FactPatchRegistry(storage_dir=storage_dir)
        patches = await reg2.get_active_patches()
        assert len(patches) == 1
        assert patches[0].override_value == "3.12"
        assert "3.10" in patches[0].anti_bias_patterns


class TestFactProjectionInterceptor:
    @pytest.mark.asyncio
    async def test_project_context_matches_and_generates_guardrail(self) -> None:
        registry = FactPatchRegistry()
        await registry.register_patch(
            entity="git_branch",
            attribute="default",
            override_value="main",
            statement="All repositories strictly use main branch",
            anti_bias_patterns=["master"],
        )

        interceptor = FactProjectionInterceptor(registry=registry)

        # Trigger by mentioning entity / concept
        result = await interceptor.project_context("Please create a git_branch and push")
        assert len(result.matched_patches) == 1
        assert "master" in result.suppressed_bias_tokens
        assert "[NON-NEGOTIABLE USER FACT CORRECTION - ZERO TOLERANCE]" in result.injection_prompt
        assert "MUST use 'main'" in result.injection_prompt
        assert "STRICTLY FORBIDDEN OBSOLETE PATTERNS: ['master']" in result.injection_prompt

    @pytest.mark.asyncio
    async def test_project_context_ignores_irrelevant_tasks(self) -> None:
        registry = FactPatchRegistry()
        await registry.register_patch(
            entity="git_branch",
            attribute="default",
            override_value="main",
            statement="Use main branch",
        )

        interceptor = FactProjectionInterceptor(registry=registry)

        result = await interceptor.project_context("Write a delicious lasagna recipe with cheese")
        assert len(result.matched_patches) == 0
        assert result.injection_prompt == ""

    def test_adversarial_conflict_probe(self) -> None:
        interceptor = FactProjectionInterceptor()

        patch = FactPatch(
            entity="auth_driver",
            attribute="protocol",
            override_value="oauth2_pkce",
            statement="Strictly use oauth2_pkce, never basic_auth",
            anti_bias_patterns=["basic_auth"],
        )

        # 1. Successful compliance response
        valid_response = "We will configure the client using oauth2_pkce authentication flow."
        probe_ok = interceptor.probe_response(patch, valid_response)
        assert probe_ok.probe_passed is True
        assert probe_ok.anti_bias_detected is False

        # 2. Leaked prior bias response (even if mentioning correct value)
        contaminated_response = "We can use oauth2_pkce, but falling back to basic_auth for compatibility."
        probe_fail = interceptor.probe_response(patch, contaminated_response)
        assert probe_fail.probe_passed is False
        assert probe_fail.anti_bias_detected is True
        assert "[LEAKED_PRIOR_BIAS]" in probe_fail.observed_value
