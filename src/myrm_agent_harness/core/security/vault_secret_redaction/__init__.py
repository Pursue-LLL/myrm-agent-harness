"""Always-on vault secret dynamic redaction suite.

Exports public interfaces and implementations for sensitive token scrubbing.
"""

from __future__ import annotations

from .facade import (
    VaultSecretRedactionFacade,
    get_vault_secret_redaction_facade,
)
from .pipeline import AlwaysOnVaultSecretRedactor
from .stream_scrubber import (
    SecretStreamScrubber,
    strip_ansi_codes,
)
from .types import (
    RedactionResult,
    RedactionScope,
    SecretEntry,
    SecretSourceType,
    StreamScrubChunkResult,
    VaultSecretRedactionConfig,
)

__all__ = [
    "AlwaysOnVaultSecretRedactor",
    "RedactionResult",
    "RedactionScope",
    "SecretEntry",
    "SecretSourceType",
    "SecretStreamScrubber",
    "StreamScrubChunkResult",
    "VaultSecretRedactionConfig",
    "VaultSecretRedactionFacade",
    "get_vault_secret_redaction_facade",
    "strip_ansi_codes",
]
