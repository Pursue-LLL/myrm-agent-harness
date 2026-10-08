"""
[POS] tests/unit/test_introspection_shield_suite.py
[INPUT] pytest, tmp_path, pathlib
[OUTPUT] Unit tests for Agent Runtime Introspection Shield & Decoupled Workspace Template Suite

Validates blackhole containment, fake-root redirection, template hydration, and suite metrics.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.core.security.introspection_shield import (
    DecoupledTemplateStandard,
    IntrospectionBlackholePolicy,
    IntrospectionProbeType,
    IntrospectionShieldSuite,
    ShieldActionEnum,
)


def test_blackhole_policy_safe_and_blocked_paths(tmp_path: Path) -> None:
    """Validate that safe paths are allowed while host introspection probes are intercepted."""
    policy = IntrospectionBlackholePolicy(enable_fake_root=False)

    # 1. Safe workspace file
    safe_res = policy.evaluate_path("src/app/main.py", workspace_root=tmp_path)
    assert not safe_res.is_blocked
    assert safe_res.action_taken == ShieldActionEnum.ALLOW_UNRESTRICTED
    assert safe_res.probe_type is None

    # 2. Block /opt/hatch Meta Muse leak path
    muse_res = policy.evaluate_path("/opt/hatch/internal_soul.yaml", workspace_root=tmp_path)
    assert muse_res.is_blocked
    assert muse_res.action_taken == ShieldActionEnum.BLOCK_BLACKHOLE
    assert muse_res.probe_type == IntrospectionProbeType.HOST_PATH_PROBE

    # 3. Block /proc/self/environ
    env_res = policy.evaluate_path("/proc/self/environ", workspace_root=tmp_path)
    assert env_res.is_blocked
    assert env_res.action_taken == ShieldActionEnum.BLOCK_BLACKHOLE
    assert env_res.probe_type == IntrospectionProbeType.ENVIRONMENT_LEAK_PROBE

    # 4. Block framework internal source
    harness_res = policy.evaluate_path(
        "/usr/local/lib/python3.13/site-packages/myrm_agent_harness/agent/runtime.py",
        workspace_root=tmp_path,
    )
    assert harness_res.is_blocked
    assert harness_res.probe_type == IntrospectionProbeType.FRAMEWORK_SOURCE_SNOOPING


def test_blackhole_fake_root_redirection(tmp_path: Path) -> None:
    """Validate fake-root virtualization when enable_fake_root is true and workspace_root is present."""
    policy = IntrospectionBlackholePolicy(enable_fake_root=True)

    target_probe = "/opt/hatch/config.json"
    result = policy.evaluate_path(target_probe, workspace_root=tmp_path)

    assert result.is_blocked
    assert result.action_taken == ShieldActionEnum.FAKE_ROOT_REDIRECT
    assert "virtual_root/config.json" in result.sanitized_path.replace("\\", "/")


def test_custom_blackhole_pattern_registration(tmp_path: Path) -> None:
    """Validate registering dynamic custom blackhole patterns."""
    policy = IntrospectionBlackholePolicy(enable_fake_root=False)
    policy.add_custom_pattern("/private/tenant_secrets/**")

    probe_res = policy.evaluate_path("/private/tenant_secrets/keys.json", workspace_root=tmp_path)
    assert probe_res.is_blocked
    assert probe_res.action_taken == ShieldActionEnum.BLOCK_BLACKHOLE


def test_decoupled_template_hydration_and_scaffolding(tmp_path: Path) -> None:
    """Validate scaffolding and hydration of decoupled standards (SOUL, USER, IDENTITY, etc.)."""
    suite = IntrospectionShieldSuite()

    # 1. Scaffold defaults in empty directory
    created = suite.scaffold_workspace_templates(tmp_path)
    assert len(created) == 5
    assert (tmp_path / "SOUL.md").exists()
    assert (tmp_path / "USER.md").exists()
    assert (tmp_path / "IDENTITY.md").exists()
    assert (tmp_path / "BOOTSTRAP.md").exists()
    assert (tmp_path / "HEARTBEAT.md").exists()

    # 2. Hydrate workspace
    hydrated = suite.hydrate_workspace_templates(tmp_path)
    assert len(hydrated) == 5
    assert DecoupledTemplateStandard.SOUL in hydrated
    assert "Core Principles" in hydrated[DecoupledTemplateStandard.SOUL].content

    # 3. Prompt context composition
    prompt_ctx = suite.build_prompt_context(hydrated)
    assert "<workspace_standards>" in prompt_ctx
    assert "<standard type=\"SOUL\"" in prompt_ctx
    assert "</workspace_standards>" in prompt_ctx


def test_introspection_suite_end_to_end_metrics(tmp_path: Path) -> None:
    """Validate suite-level metrics and end-to-end integration."""
    suite = IntrospectionShieldSuite()

    # Safe probe
    suite.evaluate_path("index.html", workspace_root=tmp_path)
    # Blocked probes
    suite.evaluate_path("/opt/deployment/manifest.yaml", workspace_root=tmp_path)
    suite.evaluate_path("/etc/shadow", workspace_root=None)

    # Scaffolding
    suite.scaffold_workspace_templates(tmp_path)
    suite.hydrate_workspace_templates(tmp_path)

    metrics = suite.metrics
    assert metrics.probes_evaluated == 3
    assert metrics.probes_blocked == 2
    assert metrics.fake_root_redirects == 1
    assert metrics.scaffolds_generated == 5
    assert metrics.templates_hydrated == 5
