"""SSRF / local-mode behavior for ImageValidator reference URLs."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.image.validator import ImageValidator, ValidationError


def test_localhost_blocked_when_ssrf_enabled() -> None:
    validator = ImageValidator(ssrf_protection=True, allow_private_networks=False)
    with pytest.raises(ValidationError, match="not allowed"):
        validator.validate_reference_url("http://localhost:8080/image.png")


def test_localhost_allowed_in_local_mode() -> None:
    validator = ImageValidator(ssrf_protection=True, allow_private_networks=True)
    validator.validate_reference_url("http://localhost:8080/image.png")


def test_ssrf_rejects_missing_hostname() -> None:
    validator = ImageValidator(ssrf_protection=True, allow_private_networks=False)
    with pytest.raises(ValidationError, match="no hostname"):
        validator.validate_reference_url("http:///image.png")


def test_ssrf_disabled_skips_all_checks() -> None:
    validator = ImageValidator(ssrf_protection=False, allow_private_networks=False)
    validator.validate_reference_url("http://127.0.0.1/image.png")


def test_ssrf_blocks_loopback_ip_literal() -> None:
    validator = ImageValidator(ssrf_protection=True, allow_private_networks=False)
    with pytest.raises(ValidationError, match="private/loopback"):
        validator.validate_reference_url("http://127.0.0.1/image.png")

