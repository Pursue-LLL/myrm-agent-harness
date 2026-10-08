import hashlib
import hmac
import threading
import time
import uuid

from .types import AgentDigitalCertificateSpec, CertificateStatusEnum


class AgentCertificateAuthority:
    """Certificate Authority responsible for minting and signing agent digital certificates."""

    DEFAULT_ISSUER_DN = "CN=Myrm Root Trust CA, O=Myrm Architecture, C=CN"

    def __init__(
        self,
        issuer_dn: str = DEFAULT_ISSUER_DN,
        ca_signing_secret: str = "MYRM_CA_ROOT_PRIVATE_SIGNING_KEY_2026",
    ) -> None:
        self._issuer_dn = issuer_dn
        self._signing_secret = ca_signing_secret.encode("utf-8")
        self._lock = threading.Lock()
        self._serial_counter: int = 1000000

    @property
    def issuer_dn(self) -> str:
        """Distinguished name of the certificate issuer."""
        return self._issuer_dn

    def mint_certificate(
        self,
        agent_id: str,
        subject_dn: str,
        validity_days: int = 365,
        attributes: dict[str, str] | None = None,
    ) -> AgentDigitalCertificateSpec:
        """Mint and cryptographically sign a new X.509/SM2 digital certificate for an agent."""
        with self._lock:
            self._serial_counter += 1
            serial_no = f"SN-{self._serial_counter:012X}"

        now = time.time()
        not_after = now + (validity_days * 86400)
        cert_id = f"cert-{uuid.uuid4().hex[:12]}"

        # Compute fingerprint
        fingerprint_material = f"{agent_id}|{subject_dn}|{serial_no}|{now}|{not_after}"
        fingerprint_sha256 = hashlib.sha256(fingerprint_material.encode("utf-8")).hexdigest()

        # Generate cryptographic signature
        signature_material = (
            f"{cert_id}|{agent_id}|{self._issuer_dn}|{subject_dn}|"
            f"{serial_no}|{now:.4f}|{not_after:.4f}|{fingerprint_sha256}"
        )
        signature_hex = hmac.new(
            self._signing_secret,
            signature_material.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Mock public key PEM
        mock_pub_key = (
            f"-----BEGIN AGENT PUBLIC KEY-----\n"
            f"MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA{fingerprint_sha256[:32]}\n"
            f"-----END AGENT PUBLIC KEY-----"
        )

        attrs = attributes if attributes is not None else {}

        return AgentDigitalCertificateSpec(
            cert_id=cert_id,
            agent_id=agent_id,
            issuer_dn=self._issuer_dn,
            subject_dn=subject_dn,
            serial_number=serial_no,
            fingerprint_sha256=fingerprint_sha256,
            not_before=now,
            not_after=not_after,
            status=CertificateStatusEnum.ACTIVE,
            signature_hex=signature_hex,
            public_key_pem=mock_pub_key,
            attributes=attrs,
        )

    def verify_signature(self, cert: AgentDigitalCertificateSpec) -> bool:
        """Verify the cryptographic signature of an issued certificate against the CA key."""
        signature_material = (
            f"{cert.cert_id}|{cert.agent_id}|{cert.issuer_dn}|{cert.subject_dn}|"
            f"{cert.serial_number}|{cert.not_before:.4f}|{cert.not_after:.4f}|{cert.fingerprint_sha256}"
        )
        expected_sig = hmac.new(
            self._signing_secret,
            signature_material.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(cert.signature_hex, expected_sig)
