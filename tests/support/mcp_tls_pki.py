"""Throwaway PKI for live TLS / mTLS MCP integration tests.

[INPUT]
- cryptography::x509 + hazmat primitives (POS: certificate and key generation)

[OUTPUT]
- TlsPki: file paths of a private CA, an unrelated rogue CA, a 127.0.0.1 server leaf and a client leaf (plain + passphrase-encrypted key)
- generate_tls_pki: materialise the PKI inside a pytest tmp directory
- VERIFY_FAILURE_MARKERS / ABORTED_CONNECTION_MARKERS: lowercase error-text fragments that identify TLS-layer rejections

[POS]
Harness pytest-only helper. Leaves chain to a real CA with the RFC 5280 extensions
OpenSSL's strict verification (the Python 3.13 default) demands, so live handshakes
exercise the production ``ssl.SSLContext`` construction instead of bypassing verification.
"""

from __future__ import annotations

import datetime
import ipaddress
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CLIENT_KEY_PASSPHRASE = "live-mtls-passphrase"
# OpenSSL contexts report "certificate verify failed"; the macOS system trust store reports "certificate is not trusted".
VERIFY_FAILURE_MARKERS = ("certificate verify failed", "certificate is not trusted")
# An mTLS listener drops a client without a certificate before any HTTP response, which the HTTP clients surface as an
# aborted connection (a raw TLS probe proves the listener, not the client, is what enforces client auth).
ABORTED_CONNECTION_MARKERS = ("readerror", "remoteprotocolerror", "server disconnected")
_LEAF_USAGE_FLAGS = {
    "digital_signature": True,
    "key_encipherment": True,
    "content_commitment": False,
    "data_encipherment": False,
    "key_agreement": False,
    "key_cert_sign": False,
    "crl_sign": False,
    "encipher_only": False,
    "decipher_only": False,
}
_CA_USAGE_FLAGS = {**_LEAF_USAGE_FLAGS, "key_encipherment": False, "key_cert_sign": True, "crl_sign": True}


@dataclass(frozen=True, slots=True)
class TlsPki:
    """Certificate material written to disk by :func:`generate_tls_pki`."""

    ca_cert: Path
    rogue_ca_cert: Path
    server_cert: Path
    server_key: Path
    client_cert: Path
    client_key: Path
    client_key_encrypted: Path
    client_key_passphrase: str


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _builder(
    subject: x509.Name,
    issuer: x509.Name,
    public_key: rsa.RSAPublicKey,
) -> x509.CertificateBuilder:
    now = datetime.datetime.now(datetime.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
    )


def _build_ca(common_name: str) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _new_key()
    name = _name(common_name)
    cert = (
        _builder(name, name, key.public_key())
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(**_CA_USAGE_FLAGS), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _build_leaf(
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    *,
    common_name: str,
    usage: x509.ObjectIdentifier,
    san: x509.SubjectAlternativeName | None = None,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _new_key()
    builder = (
        _builder(_name(common_name), ca_cert.subject, key.public_key())
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(**_LEAF_USAGE_FLAGS), critical=True)
        .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
    )
    if san is not None:
        builder = builder.add_extension(san, critical=False)
    return key, builder.sign(ca_key, hashes.SHA256())


def _write_cert(path: Path, cert: x509.Certificate) -> Path:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


def _write_key(path: Path, key: rsa.RSAPrivateKey, *, passphrase: str | None = None) -> Path:
    encryption: serialization.KeySerializationEncryption = (
        serialization.BestAvailableEncryption(passphrase.encode()) if passphrase else serialization.NoEncryption()
    )
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption))
    return path


def generate_tls_pki(directory: Path) -> TlsPki:
    """Create CA, rogue CA, server leaf (SAN 127.0.0.1 + localhost) and client leaf under *directory*."""
    ca_key, ca_cert = _build_ca("mcp-live-test-ca")
    _, rogue_ca_cert = _build_ca("mcp-live-rogue-ca")

    server_san = x509.SubjectAlternativeName(
        [x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")]
    )
    server_key, server_cert = _build_leaf(
        ca_key, ca_cert, common_name="127.0.0.1", usage=ExtendedKeyUsageOID.SERVER_AUTH, san=server_san
    )
    client_key, client_cert = _build_leaf(
        ca_key, ca_cert, common_name="mcp-live-client", usage=ExtendedKeyUsageOID.CLIENT_AUTH
    )

    return TlsPki(
        ca_cert=_write_cert(directory / "ca.pem", ca_cert),
        rogue_ca_cert=_write_cert(directory / "rogue-ca.pem", rogue_ca_cert),
        server_cert=_write_cert(directory / "server.crt", server_cert),
        server_key=_write_key(directory / "server.key", server_key),
        client_cert=_write_cert(directory / "client.crt", client_cert),
        client_key=_write_key(directory / "client.key", client_key),
        client_key_encrypted=_write_key(directory / "client.enc.key", client_key, passphrase=CLIENT_KEY_PASSPHRASE),
        client_key_passphrase=CLIENT_KEY_PASSPHRASE,
    )
