"""Validator for declarative marketplace manifest source pinning and capability contracts.

[INPUT]
- MarketplaceManifestItem, PlatformKind.

[OUTPUT]
- Validation confirmation or SourcePinningMissingError.

[POS]
- Harness core security engine. Ensures marketplace items declare immutable commit SHAs
  and explicit capability contracts before admission.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.core.security.marketplace_contract.types import (
    SHA1_HEX_PATTERN,
    SHA256_HEX_PATTERN,
    MarketplaceManifestItem,
    PlatformKind,
    SourcePinningMissingError,
)

logger = logging.getLogger(__name__)


class ManifestContractValidator:
    """Validates that marketplace package manifests satisfy source pinning and capability rules."""

    @staticmethod
    def is_valid_sha(sha_str: str) -> bool:
        """Check whether string is a valid SHA-1 (40 hex) or SHA-256 (64 hex) digest."""
        clean = sha_str.strip()
        return bool(SHA1_HEX_PATTERN.match(clean) or SHA256_HEX_PATTERN.match(clean))

    def validate_manifest(self, manifest: MarketplaceManifestItem) -> None:
        """Assert manifest validity, raising SourcePinningMissingError if pinning is absent or invalid."""
        if not manifest.source_sha or not self.is_valid_sha(manifest.source_sha):
            raise SourcePinningMissingError(
                f"Source Pinning Violation: Package '{manifest.package_id}' must specify an "
                f"immutable commit or release SHA digest (40-char SHA1 or 64-char SHA256). "
                f"Got: '{manifest.source_sha}'"
            )

        if not manifest.repo_url or not manifest.repo_url.startswith(("https://", "git@", "ssh://")):
            raise SourcePinningMissingError(
                f"Invalid Repository Source: Package '{manifest.package_id}' repo_url "
                f"'{manifest.repo_url}' must be a secure remote repository URL."
            )

    @staticmethod
    def is_platform_supported(
        manifest: MarketplaceManifestItem, current_platform: PlatformKind
    ) -> bool:
        """Determine whether package supports the current operating platform."""
        if PlatformKind.ALL in manifest.platforms:
            return True
        return current_platform in manifest.platforms
