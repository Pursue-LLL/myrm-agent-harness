"""Multi-encoding secret masker for redacting credentials across diverse encodings.

[INPUT]
- Environment variable dictionary containing secrets and plaintext parameters.

[OUTPUT]
- MultiEncodingSecretMasker: Redaction engine replacing multi-format secrets with masked tags.

[POS]
Multi-encoding masking engine covering raw, URL-encoded, Base64, Base64URL, and Hex representations.
"""

from __future__ import annotations

import base64
import urllib.parse
from dataclasses import dataclass

NON_SECRET_ENV_KEYS: frozenset[str] = frozenset(
    {
        "AGENT_API_URL",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "BROWSE_LAB_MAX_STEPS",
        "BROWSE_LAB_MODEL",
        "BROWSE_LAB_BASE_URL",
        "BROWSE_LAB_MODEL_PROVIDER",
        "PYTHONUNBUFFERED",
        "NO_PROXY",
        "no_proxy",
        "PATH",
        "HOME",
        "LANG",
    }
)

MIN_MASKABLE_LENGTH: int = 8


@dataclass(frozen=True)
class SecretVariant:
    needle: str
    label: str


class MultiEncodingSecretMasker:
    """Masks secret values across raw, URL-encoded, Base64, and Base64URL representations."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        self._variants: list[SecretVariant] = []
        if env:
            self._build_variants(env)

    def _build_variants(self, env: dict[str, str]) -> None:
        variants: list[SecretVariant] = []
        for key, value in env.items():
            if key in NON_SECRET_ENV_KEYS or len(value) < MIN_MASKABLE_LENGTH:
                continue

            # 1. Raw value
            variants.append(SecretVariant(needle=value, label=key))

            # 2. URL-encoded value
            url_encoded = urllib.parse.quote(value)
            if url_encoded != value:
                variants.append(SecretVariant(needle=url_encoded, label=key))

            # 3. Base64 value (stripped padding)
            raw_bytes = value.encode("utf-8")
            b64_val = base64.b64encode(raw_bytes).decode("utf-8").rstrip("=")
            if b64_val != value:
                variants.append(SecretVariant(needle=b64_val, label=key))

            # 4. Base64URL value (RFC 4648)
            b64url_val = base64.urlsafe_b64encode(raw_bytes).decode("utf-8").rstrip("=")
            if b64url_val != value and b64url_val != b64_val:
                variants.append(SecretVariant(needle=b64url_val, label=key))

            # 5. Hex lowercase and uppercase variants (e.g. for crypto keys, token hashes)
            hex_lower = raw_bytes.hex()
            if hex_lower != value:
                variants.append(SecretVariant(needle=hex_lower, label=key))
            hex_upper = hex_lower.upper()
            if hex_upper != hex_lower and hex_upper != value:
                variants.append(SecretVariant(needle=hex_upper, label=key))

        # Longest-first sorting to prevent short tokens from partially corrupting longer ones
        variants.sort(key=lambda v: len(v.needle), reverse=True)
        self._variants = variants

    @property
    def variant_count(self) -> int:
        return len(self._variants)

    def mask(self, text: str) -> tuple[str, list[str]]:
        """Mask all secret variants in text.

        Returns:
            Tuple of (masked_text, list_of_redacted_labels)
        """
        if not text or not self._variants:
            return text, []

        redacted_labels: set[str] = set()
        masked = text
        for variant in self._variants:
            if variant.needle in masked:
                masked = masked.replace(variant.needle, f"<redacted:{variant.label}>")
                redacted_labels.add(variant.label)

        return masked, sorted(list(redacted_labels))
