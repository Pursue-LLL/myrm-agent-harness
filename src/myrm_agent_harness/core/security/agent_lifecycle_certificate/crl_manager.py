import threading
import time

from .types import RevocationReasonEnum, RevocationRecord


class CertificateRevocationManager:
    """Thread-safe Certificate Revocation List (CRL) manager for emergency circuit-breaking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._revocations_by_sn: dict[str, RevocationRecord] = {}
        self._revocations_by_cert_id: dict[str, RevocationRecord] = {}

    def revoke_certificate(
        self,
        serial_number: str,
        cert_id: str,
        agent_id: str,
        reason: RevocationReasonEnum,
        revoked_by: str = "security-admin",
    ) -> RevocationRecord:
        """Add a certificate to the emergency revocation list."""
        now = time.time()
        record = RevocationRecord(
            serial_number=serial_number,
            cert_id=cert_id,
            agent_id=agent_id,
            revocation_timestamp=now,
            reason=reason,
            revoked_by=revoked_by,
        )
        with self._lock:
            self._revocations_by_sn[serial_number] = record
            self._revocations_by_cert_id[cert_id] = record
        return record

    def is_revoked(self, serial_number: str) -> bool:
        """Check if a certificate serial number is revoked."""
        with self._lock:
            return serial_number in self._revocations_by_sn

    def is_cert_id_revoked(self, cert_id: str) -> bool:
        """Check if a cert_id is revoked."""
        with self._lock:
            return cert_id in self._revocations_by_cert_id

    def get_revocation_record(self, serial_number: str) -> RevocationRecord | None:
        """Retrieve revocation record for a serial number."""
        with self._lock:
            return self._revocations_by_sn.get(serial_number)

    def get_revocation_record_by_cert_id(self, cert_id: str) -> RevocationRecord | None:
        """Retrieve revocation record by cert_id."""
        with self._lock:
            return self._revocations_by_cert_id.get(cert_id)

    def get_crl_snapshot(self) -> list[RevocationRecord]:
        """Retrieve full snapshot of currently revoked certificates."""
        with self._lock:
            return list(self._revocations_by_sn.values())

    @property
    def total_revoked(self) -> int:
        """Total count of actively revoked certificates."""
        with self._lock:
            return len(self._revocations_by_sn)
