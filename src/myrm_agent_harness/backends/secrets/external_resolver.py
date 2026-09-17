"""External secret reference resolver facade."""
from __future__ import annotations

from myrm_agent_harness.toolkits.llms.secrets import (
    ExternalSecretResolutionError,
    is_external_secret_reference,
    resolve_external_secret,
)

__all__ = [
    "ExternalSecretResolutionError",
    "is_external_secret_reference",
    "resolve_external_secret",
]
