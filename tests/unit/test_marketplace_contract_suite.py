"""Unit tests for Marketplace Manifest Source Pinning & Capability Contract Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.marketplace_contract import (
    AdmissionPolicy,
    CapabilityContract,
    DisallowedCapabilityError,
    DisallowedTierError,
    ManifestContractValidator,
    MarketplaceAdmissionGate,
    MarketplaceManifestItem,
    MarketplaceTier,
    PlatformKind,
    SourcePinningMissingError,
)


@pytest.fixture
def sample_manifest() -> MarketplaceManifestItem:
    return MarketplaceManifestItem(
        package_id="hermes-metamask-wallet",
        name="MetaMask Wallet Integration",
        version="1.2.0",
        repo_url="https://github.com/akugone/hermes-metamask-wallet",
        source_sha="b56d6bbf575391d172280016abf778d31c5ca8bd",  # 40-char SHA1
        tier=MarketplaceTier.COMMUNITY,
        requires_host=">=0.21.0",
        platforms=(PlatformKind.MACOS, PlatformKind.LINUX),
        capabilities=CapabilityContract(
            provides_tools=("mm_status", "mm_setup", "mm_balance"),
            provides_hooks=("pre_tool_call", "post_tool_call"),
            requires_env=("METAMASK_RPC_URL",),
        ),
        publisher="akugone",
    )


def test_valid_manifest_source_pinning(sample_manifest: MarketplaceManifestItem) -> None:
    validator = ManifestContractValidator()
    validator.validate_manifest(sample_manifest)
    assert ManifestContractValidator.is_platform_supported(sample_manifest, PlatformKind.MACOS)
    assert ManifestContractValidator.is_platform_supported(sample_manifest, PlatformKind.LINUX)
    assert not ManifestContractValidator.is_platform_supported(sample_manifest, PlatformKind.WINDOWS)


def test_missing_or_mutable_source_pin_fails() -> None:
    validator = ManifestContractValidator()

    # Attempting to use mutable tag or branch name instead of immutable SHA digest
    invalid_manifest = MarketplaceManifestItem(
        package_id="bad-pkg",
        name="Bad Package",
        version="0.1.0",
        repo_url="https://github.com/someone/bad-pkg",
        source_sha="v1.0.0-latest",  # Not a valid SHA
        tier=MarketplaceTier.COMMUNITY,
    )

    with pytest.raises(SourcePinningMissingError, match="must specify an immutable commit"):
        validator.validate_manifest(invalid_manifest)


def test_org_admission_allowed_sources_restriction(
    sample_manifest: MarketplaceManifestItem,
) -> None:
    # Organization policy restricts packages to trusted internal org repos
    policy = AdmissionPolicy(
        allowed_sources=("https://github.com/trusted-org/",),
        enforce_strict_pinning=True,
    )
    gate = MarketplaceAdmissionGate(policy=policy)

    verdict = gate.evaluate_manifest(sample_manifest)
    assert verdict.is_admitted is False
    assert any("not in allowed sources" in v for v in verdict.violations)

    with pytest.raises(DisallowedTierError):
        gate.assert_admission(sample_manifest)


def test_org_admission_tier_restriction(sample_manifest: MarketplaceManifestItem) -> None:
    # Organization restricts packages strictly to OFFICIAL and VERIFIED tiers
    policy = AdmissionPolicy(
        allowed_tiers=(MarketplaceTier.OFFICIAL, MarketplaceTier.VERIFIED),
        enforce_strict_pinning=True,
    )
    gate = MarketplaceAdmissionGate(policy=policy)

    verdict = gate.evaluate_manifest(sample_manifest)
    assert verdict.is_admitted is False
    assert any("Tier 'COMMUNITY' is disallowed" in v for v in verdict.violations)

    with pytest.raises(DisallowedTierError, match="Tier 'COMMUNITY' is disallowed"):
        gate.assert_admission(sample_manifest)


def test_org_admission_forbidden_capability() -> None:
    manifest_with_middleware = MarketplaceManifestItem(
        package_id="proxy-injector",
        name="Proxy Injector",
        version="1.0.0",
        repo_url="https://github.com/org/proxy-injector",
        source_sha="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # 64-char SHA256
        tier=MarketplaceTier.VERIFIED,
        capabilities=CapabilityContract(
            provides_middleware=("network_traffic_intercept_middleware",),
        ),
    )

    # Organization policy forbids plugins injecting middleware
    policy = AdmissionPolicy(
        disallowed_capabilities=("network_traffic_intercept_middleware",),
        enforce_strict_pinning=True,
    )
    gate = MarketplaceAdmissionGate(policy=policy)

    verdict = gate.evaluate_manifest(manifest_with_middleware)
    assert verdict.is_admitted is False
    assert any("Forbidden middleware capability requested" in v for v in verdict.violations)

    with pytest.raises(DisallowedCapabilityError, match="Forbidden middleware capability"):
        gate.assert_admission(manifest_with_middleware)
