"""Unit tests for Verifiable Cryptographic Erasure and Complete Data Portability Suite."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.core.security.data_erasure_portability.crypto_erasure import (
    CryptographicErasureEngine,
)
from myrm_agent_harness.core.security.data_erasure_portability.portability import (
    DataPortabilityExporter,
)
from myrm_agent_harness.core.security.data_erasure_portability.shredder import (
    SecureStorageShredder,
)
from myrm_agent_harness.core.security.data_erasure_portability.types import (
    DataPortabilityBundle,
    DeletionCertificate,
    ErasureMethod,
    ShreddingPassConfig,
)


def test_shred_bytes_buffer() -> None:
    shredder = SecureStorageShredder()
    buf = bytearray(b"super_secret_master_key_1234567")
    shredder.shred_bytes_buffer(buf)
    assert buf == bytearray(len(buf))


def test_shred_file(tmp_path: Path) -> None:
    shredder = SecureStorageShredder()
    secret_file = tmp_path / "sensitive_sqlite.db"
    content = b"CRITICAL_DATABASE_PAYLOAD_CONTENT" * 100
    secret_file.write_bytes(content)

    assert secret_file.exists()
    bytes_shredded = shredder.shred_file(secret_file, config=ShreddingPassConfig(passes=3))

    assert bytes_shredded == len(content)
    assert not secret_file.exists()


def test_shred_directory(tmp_path: Path) -> None:
    shredder = SecureStorageShredder()
    target_dir = tmp_path / "user_workspace"
    sub_dir = target_dir / "memories"
    sub_dir.mkdir(parents=True)

    file1 = target_dir / "state.json"
    file2 = sub_dir / "vectors.bin"
    file1.write_text('{"user": "alice"}')
    file2.write_bytes(b"\x01\x02\x03\x04" * 10)

    files_count, bytes_count = shredder.shred_directory(target_dir)
    assert files_count == 2
    assert bytes_count > 0
    assert not target_dir.exists()


def test_cryptographic_erasure_and_certificate_flow() -> None:
    engine = CryptographicErasureEngine()
    tenant_id = "tenant-enterprise-99"

    # 1. Register DEK
    fp = engine.register_tenant_key(tenant_id)
    assert len(fp) == 64
    assert engine.get_tenant_key_fingerprint(tenant_id) == fp

    # 2. Execute cryptographic erasure
    result = engine.execute_cryptographic_erasure(
        tenant_id=tenant_id,
        target_resource_types=["CONVERSATIONS", "VECTORS", "MEMORY"],
        shredded_bytes=1048576,
        signer_identity="myrm-trust-ledger",
    )

    assert result.success is True
    assert result.erasure_method == ErasureMethod.CRYPTOGRAPHIC
    assert result.certificate is not None
    cert = result.certificate

    # Key must be destroyed
    assert engine.get_tenant_key_fingerprint(tenant_id) is None

    # 3. Certificate verification
    assert engine.verify_deletion_certificate(cert) is True

    # 4. Tampered certificate must be rejected
    tampered_cert = DeletionCertificate(
        certificate_id=cert.certificate_id,
        tenant_id=cert.tenant_id,
        erasure_method=cert.erasure_method,
        target_resource_types=cert.target_resource_types,
        shredded_bytes=999999999,  # tampered byte count
        payload_checksum_prior=cert.payload_checksum_prior,
        timestamp=cert.timestamp,
        signer_identity=cert.signer_identity,
        certificate_signature=cert.certificate_signature,
    )
    assert engine.verify_deletion_certificate(tampered_cert) is False


def test_data_portability_bundle_export_and_verify() -> None:
    exporter = DataPortabilityExporter()
    tenant_id = "tenant-user-42"
    conversations = [{"session_id": "s1", "text": "hello agent"}]
    memories = [{"key": "user_role", "value": "architect"}]
    agent_configs = [{"agent_id": "default", "model": "gpt-5"}]

    bundle = exporter.export_bundle(
        tenant_id=tenant_id,
        conversations=conversations,
        memory_entries=memories,
        agent_configs=agent_configs,
    )

    assert bundle.tenant_id == tenant_id
    assert len(bundle.bundle_sha256) == 64
    assert len(bundle.bundle_signature) == 64

    # Verify legitimate bundle
    assert exporter.verify_bundle_integrity(bundle) is True

    # Tampered bundle contents
    tampered_bundle = DataPortabilityBundle(
        bundle_id=bundle.bundle_id,
        tenant_id=bundle.tenant_id,
        exported_at=bundle.exported_at,
        conversations=[{"session_id": "s1", "text": "tampered content"}],
        memory_entries=bundle.memory_entries,
        agent_configs=bundle.agent_configs,
        bundle_sha256=bundle.bundle_sha256,
        bundle_signature=bundle.bundle_signature,
    )
    assert exporter.verify_bundle_integrity(tampered_bundle) is False
