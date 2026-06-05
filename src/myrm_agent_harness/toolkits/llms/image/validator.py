"""Four-layer image generation request validator.

[INPUT]
- types::ModelProfile, get_profile (POS: Model capability lookup)

[OUTPUT]
- ImageValidator: Stateless request validator
- ValidationError: Raised when validation fails

[POS]
Pre-call validation that rejects invalid image generation requests
before they reach the remote API.  Four defence layers:
  L1 Prompt   — empty/length/control-char checks
  L2 Capability — request params vs ModelProfile constraints
  L3 Input    — MIME allowlist + file size limit for edit images
  L4 SSRF     — block private/internal host URLs (optional)
"""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .types import ModelProfile

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

ALLOWED_MIME_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    }
)

MAX_INPUT_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

_PRIVATE_TLDS = frozenset({"localhost", "internal", "local"})


class ValidationError(Exception):
    """Raised when image generation request validation fails."""


class ImageValidator:
    """Stateless four-layer image generation request validator.

    Instantiate once, call ``validate_generate`` or ``validate_edit``
    per request.  Pass ``ssrf_protection=True`` to enable L4 checks.
    """

    def __init__(self, *, ssrf_protection: bool = False) -> None:
        self._ssrf = ssrf_protection

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_generate(
        self,
        prompt: str,
        *,
        profile: ModelProfile | None,
        n: int = 1,
        size: str | None = None,
    ) -> None:
        """Validate a generate request.  Raises ``ValidationError``."""
        self._l1_prompt(prompt, profile)
        if profile:
            self._l2_capability_generate(profile, n=n, size=size)

    def validate_edit(
        self,
        prompt: str,
        *,
        profile: ModelProfile | None,
        image_mime: str | None = None,
        image_size_bytes: int | None = None,
        image_url: str | None = None,
        n: int = 1,
        size: str | None = None,
    ) -> None:
        """Validate an edit request.  Raises ``ValidationError``."""
        self._l1_prompt(prompt, profile)
        if profile:
            self._l2_capability_edit(profile, n=n, size=size)
        self._l3_input(image_mime, image_size_bytes)
        if image_url:
            self._l4_ssrf(image_url)

    # ------------------------------------------------------------------
    # L1: Prompt validation
    # ------------------------------------------------------------------

    @staticmethod
    def _l1_prompt(prompt: str, profile: ModelProfile | None) -> None:
        if not prompt or not prompt.strip():
            raise ValidationError("Prompt must not be empty")

        max_len = profile.max_prompt_length if profile else 4000
        if len(prompt) > max_len:
            raise ValidationError(f"Prompt length {len(prompt)} exceeds maximum {max_len}")

        if _CONTROL_CHAR_RE.search(prompt):
            raise ValidationError("Prompt contains invalid control characters")

    # ------------------------------------------------------------------
    # L2: Capability validation
    # ------------------------------------------------------------------

    @staticmethod
    def _l2_capability_generate(
        profile: ModelProfile,
        *,
        n: int,
        size: str | None,
    ) -> None:
        if n > profile.max_count:
            raise ValidationError(f"Requested {n} images, model {profile.name} supports max {profile.max_count}")

        if (
            size
            and profile.allowed_sizes
            and size not in profile.allowed_sizes
            and (not profile.allowed_aspect_ratios or size not in profile.allowed_aspect_ratios)
        ):
            raise ValidationError(
                f"Size '{size}' not supported by {profile.name}. "
                f"Allowed sizes: {sorted(profile.allowed_sizes)}"
                + (f", aspect ratios: {sorted(profile.allowed_aspect_ratios)}" if profile.allowed_aspect_ratios else "")
            )

    @staticmethod
    def _l2_capability_edit(
        profile: ModelProfile,
        *,
        n: int,
        size: str | None,
    ) -> None:
        if not profile.supports_edit:
            raise ValidationError(f"Model {profile.name} does not support image editing")
        ImageValidator._l2_capability_generate(profile, n=n, size=size)

    # ------------------------------------------------------------------
    # L3: Input media validation
    # ------------------------------------------------------------------

    @staticmethod
    def _l3_input(
        mime_type: str | None,
        size_bytes: int | None,
    ) -> None:
        if mime_type and mime_type not in ALLOWED_MIME_TYPES:
            raise ValidationError(f"MIME type '{mime_type}' not allowed. Accepted: {sorted(ALLOWED_MIME_TYPES)}")
        if size_bytes is not None and size_bytes > MAX_INPUT_IMAGE_BYTES:
            max_mb = MAX_INPUT_IMAGE_BYTES / (1024 * 1024)
            actual_mb = size_bytes / (1024 * 1024)
            raise ValidationError(f"Input image {actual_mb:.1f}MB exceeds limit of {max_mb:.0f}MB")

    # ------------------------------------------------------------------
    # L4: SSRF protection (optional)
    # ------------------------------------------------------------------

    def validate_reference_url(self, url: str) -> None:
        """Validate a reference image URL (always applies SSRF check)."""
        self._l4_ssrf(url)

    def _l4_ssrf(self, url: str) -> None:
        if not self._ssrf:
            return

        try:
            parsed = urlparse(url)
        except Exception:
            raise ValidationError(f"Malformed URL: {url[:100]}") from None

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise ValidationError("URL has no hostname")

        for tld in _PRIVATE_TLDS:
            if hostname == tld or hostname.endswith(f".{tld}"):
                raise ValidationError(f"URL hostname '{hostname}' is not allowed")

        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValidationError(f"URL resolves to private/loopback address: {hostname}")
        except ValueError:
            pass
