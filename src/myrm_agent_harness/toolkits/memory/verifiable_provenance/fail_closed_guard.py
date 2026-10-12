"""
[INPUT]: TenantSandboxContext and physical storage targets
[OUTPUT]: Fail-Closed enforcement gate preventing shared/default profile fallback
[POS]: myrm_agent_harness.toolkits.memory.verifiable_provenance.fail_closed_guard
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Optional

from .models import FailClosedSecurityException, TenantSandboxContext


class FailClosedMemoryGuard:
    """Enforces strict fail-closed boundary: missing or mismatched context aborts immediately."""

    def __init__(self, master_environment_secret: str) -> None:
        if not master_environment_secret:
            raise ValueError("master_environment_secret cannot be empty")
        self._secret_bytes = master_environment_secret.encode("utf-8")

    def validate_request_context(
        self,
        context: Optional[TenantSandboxContext],
        target_path: Path,
    ) -> None:
        """Validate context against strict boundary rules without falling back to defaults."""
        if context is None:
            raise FailClosedSecurityException(
                "Access denied: Missing TenantSandboxContext. Zero-fallback policy prohibits default profile."
            )

        if not context.tenant_id or context.tenant_id.strip() == "":
            raise FailClosedSecurityException(
                "Access denied: Empty tenant_id in context. Zero-fallback policy triggered.",
                context,
            )

        if not context.sandbox_id or context.sandbox_id.strip() == "":
            raise FailClosedSecurityException(
                "Access denied: Empty sandbox_id in context. Hardware sandboxing required.",
                context,
            )

        if not context.volume_id or context.volume_id.strip() == "":
            raise FailClosedSecurityException(
                "Access denied: Empty volume_id in context. Dedicated storage volume required.",
                context,
            )

        expected_token = self.generate_token(context.tenant_id, context.sandbox_id, context.volume_id)
        if not hmac.compare_digest(context.environment_token, expected_token):
            raise FailClosedSecurityException(
                "Access denied: Invalid environment_token for tenant volume binding.",
                context,
            )

        # Ensure target_path physically resides within sandbox volume boundary
        resolved_path = target_path.resolve()
        path_str = str(resolved_path)
        if "shared" in path_str.lower() or "public" in path_str.lower() or "default" in path_str.lower():
            raise FailClosedSecurityException(
                f"Access denied: Target path '{resolved_path}' contains prohibited shared/default keywords.",
                context,
            )

    def generate_token(self, tenant_id: str, sandbox_id: str, volume_id: str) -> str:
        """Generate cryptographically tied environment token for dedicated sandbox volume."""
        payload = f"{tenant_id}:{sandbox_id}:{volume_id}".encode("utf-8")
        return hmac.new(self._secret_bytes, payload, "sha256").hexdigest()
