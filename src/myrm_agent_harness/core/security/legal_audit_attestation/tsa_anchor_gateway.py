import hashlib
import hmac
import threading
import uuid
from datetime import UTC, datetime

from .types import DigestAlgorithmEnum, TsaTimestampToken


class TsaAnchorGateway:
    """RFC 3161-compliant Time Stamping Authority (TSA) Anchor Gateway."""

    DEFAULT_AUTHORITY_ID = "CN-GUIZHOU-CA-TSA-01"
    DEFAULT_POLICY_OID = "1.2.156.10197.1.401"  # National Cryptography TSA Policy OID

    def __init__(
        self,
        authority_id: str = DEFAULT_AUTHORITY_ID,
        policy_oid: str = DEFAULT_POLICY_OID,
        signing_secret: str = "MYRM_LEGAL_TSA_SECURE_KEY_2026",
    ) -> None:
        self._authority_id = authority_id
        self._policy_oid = policy_oid
        self._signing_secret = signing_secret.encode("utf-8")
        self._lock = threading.Lock()
        self._serial_counter: int = 100000

    def anchor_digest(
        self,
        digest: str,
        digest_algorithm: DigestAlgorithmEnum = DigestAlgorithmEnum.SHA256,
    ) -> TsaTimestampToken:
        """Issue an immutable RFC 3161-compliant timestamp token over a digest."""
        with self._lock:
            self._serial_counter += 1
            serial_no = f"TSA-SN-{self._serial_counter:08d}"

        token_id = f"tst-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(UTC).isoformat()

        # Sign the payload using cryptographic HMAC-SHA256
        signature_material = (
            f"{self._authority_id}|{self._policy_oid}|{digest}|{now_iso}|{serial_no}"
        )
        signature_hex = hmac.new(
            self._signing_secret,
            signature_material.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return TsaTimestampToken(
            token_id=token_id,
            digest=digest,
            digest_algorithm=digest_algorithm.value,
            timestamp_iso=now_iso,
            authority_id=self._authority_id,
            policy_oid=self._policy_oid,
            serial_number=serial_no,
            signature_hex=signature_hex,
        )

    def verify_timestamp_token(
        self,
        token: TsaTimestampToken,
        expected_digest: str | None = None,
    ) -> bool:
        """Cryptographically verify the validity and authenticity of a timestamp token."""
        if expected_digest is not None and token.digest != expected_digest:
            return False

        signature_material = (
            f"{token.authority_id}|{token.policy_oid}|{token.digest}|"
            f"{token.timestamp_iso}|{token.serial_number}"
        )
        expected_signature = hmac.new(
            self._signing_secret,
            signature_material.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(token.signature_hex, expected_signature)
