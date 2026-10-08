"""Static Preflight Configuration Validator with Strict Unknown Key Rejection."""

from __future__ import annotations

import json
from typing import cast

from .types import (
    ConfigSourceTier,
    DiagnosticCheckResult,
    MyrmProjectConfigSchema,
    PreflightGateError,
)

_KNOWN_CONFIG_KEYS = frozenset(
    {
        "version",
        "model_tier",
        "execution_timeout",
        "allow_network",
        "cache_write_read_ratio",
        "sandbox_enabled",
        "anti_exfiltration_guard",
        "audit_logging",
        "custom_rules",
        "description",
    }
)

_SUPPORTED_VERSIONS = frozenset({"1.0"})


class PreflightConfigValidator:
    """Validates configuration against strict schemas, rejecting unknown keys and verifying boundaries."""

    def __init__(self, require_all_enabled: bool = False) -> None:
        self.require_all_enabled = require_all_enabled

    def validate_raw_dict(
        self,
        raw_data: dict[str, object],
        applied_tier: ConfigSourceTier = ConfigSourceTier.LOCAL_PROJECT_TRUSTED,
    ) -> DiagnosticCheckResult:
        """Validate raw dictionary from config file, checking for unknown keys and validity."""
        errors: list[str] = []
        unknown_keys: list[str] = []

        # 1. Unknown Key Detection (Strict Disallowance)
        for key in raw_data:
            if key not in _KNOWN_CONFIG_KEYS:
                unknown_keys.append(key)
                errors.append(
                    f"Unknown configuration key '{key}' is forbidden by preflight gate"
                )

        # 2. Version Verification
        version_val = str(raw_data.get("version", "1.0"))
        if version_val not in _SUPPORTED_VERSIONS:
            errors.append(
                f"Unsupported configuration version '{version_val}'. Supported versions: {sorted(_SUPPORTED_VERSIONS)}"
            )

        # 3. Numeric & Ratio Bounds Verification
        exec_timeout_raw = raw_data.get("execution_timeout", 30.0)
        exec_timeout = 30.0
        try:
            exec_timeout = float(cast(float | int | str, exec_timeout_raw))
            if exec_timeout <= 0:
                errors.append(
                    f"execution_timeout must be greater than 0, got {exec_timeout}"
                )
        except (ValueError, TypeError):
            errors.append(
                f"Invalid execution_timeout type: {exec_timeout_raw!r}"
            )

        ratio_raw = raw_data.get("cache_write_read_ratio", 1.0)
        ratio = 1.0
        try:
            ratio = float(cast(float | int | str, ratio_raw))
            if ratio < 0.0:
                errors.append(
                    f"cache_write_read_ratio must be >= 0.0, got {ratio}"
                )
        except (ValueError, TypeError):
            errors.append(
                f"Invalid cache_write_read_ratio type: {ratio_raw!r}"
            )

        # 4. Mandatory Security Features Check
        sandbox_enabled = bool(raw_data.get("sandbox_enabled", True))
        anti_exfil = bool(raw_data.get("anti_exfiltration_guard", True))
        audit_logging = bool(raw_data.get("audit_logging", True))

        all_mandatory_enabled = (
            sandbox_enabled and anti_exfil and audit_logging
        )
        if self.require_all_enabled and not all_mandatory_enabled:
            missing: list[str] = []
            if not sandbox_enabled:
                missing.append("sandbox_enabled")
            if not anti_exfil:
                missing.append("anti_exfiltration_guard")
            if not audit_logging:
                missing.append("audit_logging")
            errors.append(
                f"--require-all-enabled assertion failed: mandatory security features disabled: {missing}"
            )

        # 5. Build parsed schema
        custom_rules_raw = raw_data.get("custom_rules", ())
        custom_rules_tuple: tuple[str, ...] = ()
        if isinstance(custom_rules_raw, (list, tuple)):
            custom_rules_tuple = tuple(str(r) for r in custom_rules_raw)

        effective_config = MyrmProjectConfigSchema(
            version=version_val,
            model_tier=str(raw_data.get("model_tier", "standard")),
            execution_timeout=exec_timeout,
            allow_network=bool(raw_data.get("allow_network", False)),
            cache_write_read_ratio=ratio,
            sandbox_enabled=sandbox_enabled,
            anti_exfiltration_guard=anti_exfil,
            audit_logging=audit_logging,
            custom_rules=custom_rules_tuple,
            description=str(raw_data.get("description", "")),
        )

        is_valid = len(errors) == 0
        return DiagnosticCheckResult(
            is_valid=is_valid,
            version=version_val,
            unknown_keys=tuple(unknown_keys),
            validation_errors=tuple(errors),
            applied_tier=applied_tier,
            effective_config=effective_config,
            all_mandatory_features_enabled=all_mandatory_enabled,
        )

    def validate_json_string(
        self,
        json_content: str,
        applied_tier: ConfigSourceTier = ConfigSourceTier.LOCAL_PROJECT_TRUSTED,
    ) -> DiagnosticCheckResult:
        """Parse and validate JSON string directly."""
        try:
            parsed = json.loads(json_content)
        except json.JSONDecodeError as exc:
            return DiagnosticCheckResult(
                is_valid=False,
                version="unknown",
                unknown_keys=(),
                validation_errors=(f"Malformed JSON syntax: {exc}",),
                applied_tier=applied_tier,
                effective_config=MyrmProjectConfigSchema(),
                all_mandatory_features_enabled=False,
            )

        if not isinstance(parsed, dict):
            return DiagnosticCheckResult(
                is_valid=False,
                version="unknown",
                unknown_keys=(),
                validation_errors=("Root JSON must be an object/dict",),
                applied_tier=applied_tier,
                effective_config=MyrmProjectConfigSchema(),
                all_mandatory_features_enabled=False,
            )

        return self.validate_raw_dict(
            cast(dict[str, object], parsed), applied_tier
        )

    def assert_valid(self, result: DiagnosticCheckResult) -> None:
        """Raise PreflightGateError if result is invalid."""
        if not result.is_valid:
            error_details = "; ".join(result.validation_errors)
            raise PreflightGateError(
                f"Preflight configuration diagnostic failed: {error_details}"
            )
