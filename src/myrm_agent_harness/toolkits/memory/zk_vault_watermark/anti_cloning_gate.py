"""Sandbox and tenant bound anti-cloning security gate (Item 159).

[INPUT]
- Instance GUIDs, volume identifiers, tenant tokens, and admin unlocking passphrases.

[OUTPUT]
- Environment validation decisions and InstanceBindingFingerprint tokens.

[POS]
- Anti-cloning gate in myrm_agent_harness/toolkits/memory/zk_vault_watermark/.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone

from .models import InstanceBindingFingerprint


class SandboxAntiCloningGate:
    """Binds memory persistence volume to physical sandbox instance to prevent offline cloning."""

    def __init__(
        self,
        binding: InstanceBindingFingerprint | None = None,
    ) -> None:
        self._binding: InstanceBindingFingerprint | None = binding

    @property
    def current_binding(self) -> InstanceBindingFingerprint | None:
        """Get the active instance binding fingerprint."""
        return self._binding

    def bind_environment(
        self,
        instance_guid: str,
        volume_id: str,
        tenant_id: str,
    ) -> InstanceBindingFingerprint:
        """Affix memory vault to specific sandbox instance GUID and physical volume ID."""
        now_str = datetime.now(timezone.utc).isoformat()
        self._binding = InstanceBindingFingerprint(
            instance_guid=instance_guid,
            volume_id=volume_id,
            tenant_id=tenant_id,
            bound_at=now_str,
            is_locked=False,
        )
        return self._binding

    def verify_environment(
        self,
        current_instance_guid: str,
        current_volume_id: str,
        current_tenant_id: str,
    ) -> tuple[bool, str]:
        """Verify that current runtime matches bound hardware and sandbox fingerprint."""
        if self._binding is None:
            # First initialization automatically binds to the current sandbox
            self.bind_environment(
                instance_guid=current_instance_guid,
                volume_id=current_volume_id,
                tenant_id=current_tenant_id,
            )
            return True, "Initial sandbox binding established successfully."

        if self._binding.is_locked:
            return (
                False,
                "LOCKED: Memory vault is locked due to detected unauthorized cloning.",
            )

        # Verify instance, volume, and tenant match
        instance_ok = self._binding.instance_guid == current_instance_guid
        volume_ok = self._binding.volume_id == current_volume_id
        tenant_ok = self._binding.tenant_id == current_tenant_id

        if instance_ok and volume_ok and tenant_ok:
            return True, "Sandbox environment and volume residency verified."

        # Mismatch detected: lock vault against memory cloning
        self._binding.is_locked = True
        reasons: list[str] = []
        if not instance_ok:
            reasons.append(
                f"Instance GUID mismatch (expected: {self._binding.instance_guid}, current: {current_instance_guid})"
            )
        if not volume_ok:
            reasons.append(
                f"Volume ID mismatch (expected: {self._binding.volume_id}, current: {current_volume_id})"
            )
        if not tenant_ok:
            reasons.append(
                f"Tenant ID mismatch (expected: {self._binding.tenant_id}, current: {current_tenant_id})"
            )

        diagnostic = f"CRITICAL SECURITY ALERT: Unauthorized sandbox migration or memory cloning detected! {'; '.join(reasons)}"
        return False, diagnostic

    def unlock_and_rebind(
        self,
        provided_passphrase: str,
        expected_passphrase: str,
        new_instance_guid: str,
        new_volume_id: str,
        tenant_id: str,
    ) -> bool:
        """Unlock vault and re-bind to new sandbox instance upon authorized migration."""
        if not hmac.compare_digest(provided_passphrase, expected_passphrase):
            return False

        self.bind_environment(
            instance_guid=new_instance_guid,
            volume_id=new_volume_id,
            tenant_id=tenant_id,
        )
        return True
