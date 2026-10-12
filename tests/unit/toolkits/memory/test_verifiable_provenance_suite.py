"""
[INPUT]: Verifiable provenance components from myrm_agent_harness
[OUTPUT]: Comprehensive unit tests verifying fail-closed, residency proof, purge, and PII shield
[POS]: tests.unit.toolkits.memory.test_verifiable_provenance_suite
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.verifiable_provenance import (
    FailClosedSecurityException,
    PiiCategory,
    PurgeVerificationStatus,
    TenantSandboxContext,
    VerifiableProvenanceManager,
)


@pytest.fixture
def temp_volume_root() -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir).resolve()


@pytest.fixture
def sample_secret() -> str:
    return "test-master-environment-secret-key-12345"


@pytest.fixture
def manager(temp_volume_root: Path, sample_secret: str) -> VerifiableProvenanceManager:
    return VerifiableProvenanceManager(
        volume_root_boundary=temp_volume_root,
        master_environment_secret=sample_secret,
        overwrite_passes=3,
    )


def test_fail_closed_guard_enforcement(
    manager: VerifiableProvenanceManager,
    temp_volume_root: Path,
) -> None:
    """Verify that any missing context or illegal shared target triggers immediate hard rejection."""
    valid_file = temp_volume_root / "memory.db"
    valid_file.write_text("sample-memory-data")

    # 1. Missing context
    with pytest.raises(FailClosedSecurityException) as exc_info:
        manager.verify_and_prove_residency(valid_file, None)
    assert "Missing TenantSandboxContext" in str(exc_info.value)

    # 2. Invalid token
    invalid_ctx = TenantSandboxContext(
        tenant_id="tenant-alpha",
        sandbox_id="sb-001",
        volume_id="vol-001",
        environment_token="tampered-token",
    )
    with pytest.raises(FailClosedSecurityException) as exc_info:
        manager.verify_and_prove_residency(valid_file, invalid_ctx)
    assert "Invalid environment_token" in str(exc_info.value)

    # 3. Prohibited shared path keyword
    valid_token = manager.guard.generate_token("tenant-alpha", "sb-001", "vol-001")
    valid_ctx = TenantSandboxContext(
        tenant_id="tenant-alpha",
        sandbox_id="sb-001",
        volume_id="vol-001",
        environment_token=valid_token,
    )
    shared_path = temp_volume_root / "shared_notes.db"
    shared_path.write_text("shared-data")
    with pytest.raises(FailClosedSecurityException) as exc_info:
        manager.verify_and_prove_residency(shared_path, valid_ctx)
    assert "prohibited shared/default keywords" in str(exc_info.value)


def test_physical_residency_prover(
    manager: VerifiableProvenanceManager,
    temp_volume_root: Path,
) -> None:
    """Verify generation of immutable physical residency proof within designated volume."""
    storage_file = temp_volume_root / "isolated_memory.db"
    storage_file.write_text("confidential-agent-memory-record")

    valid_token = manager.guard.generate_token("tenant-corp", "sb-prod-9", "vol-dedicated-42")
    ctx = TenantSandboxContext(
        tenant_id="tenant-corp",
        sandbox_id="sb-prod-9",
        volume_id="vol-dedicated-42",
        environment_token=valid_token,
    )

    proof = manager.verify_and_prove_residency(storage_file, ctx, {"cluster": "sandbox-east"})
    assert proof.tenant_id == "tenant-corp"
    assert proof.sandbox_id == "sb-prod-9"
    assert proof.volume_id == "vol-dedicated-42"
    assert proof.storage_path == str(storage_file)
    assert proof.is_exclusive_volume is True
    assert proof.file_inode > 0
    assert len(proof.content_sha256) == 64
    assert proof.metadata.get("cluster") == "sandbox-east"
    assert "file_size_bytes" in proof.metadata


def test_physical_purge_destruction_engine(
    manager: VerifiableProvenanceManager,
    temp_volume_root: Path,
) -> None:
    """Verify multi-pass physical overwrite, file destruction, and receipt generation."""
    victim_file = temp_volume_root / "to_be_purged.db"
    victim_file.write_text("strictly-confidential-user-memories-1234567890")

    valid_token = manager.guard.generate_token("tenant-user-1", "sb-007", "vol-usr-1")
    ctx = TenantSandboxContext(
        tenant_id="tenant-user-1",
        sandbox_id="sb-007",
        volume_id="vol-usr-1",
        environment_token=valid_token,
    )

    receipt = manager.verify_and_purge_storage(victim_file, ctx)
    assert receipt.tenant_id == "tenant-user-1"
    assert receipt.status == PurgeVerificationStatus.VERIFIED_DESTROYED
    assert receipt.overwrite_passes == 3
    assert receipt.bytes_overwritten > 0
    assert len(receipt.destruction_digest) == 64
    assert not victim_file.exists()


def test_pre_ingest_pii_shield(manager: VerifiableProvenanceManager) -> None:
    """Verify pre-ingest interception of children identities, addresses, and financials."""
    raw_text = (
        "User context: My child's name is Alice Wonderland. "
        "Living at street: 742 Evergreen Terrace, Springfield, Zip Code: 97477. "
        "Account details: Credit card: 4532-1234-5678-9010."
    )

    result = manager.inspect_memory_content(raw_text)
    assert result.intercepted is True
    assert result.has_child_privacy_violation is True
    assert PiiCategory.CHILD_IDENTITY in result.detected_categories
    assert PiiCategory.PRECISE_RESIDENTIAL_ADDRESS in result.detected_categories
    assert PiiCategory.FINANCIAL_INSTRUMENT in result.detected_categories

    assert "[REDACTED_CHILD_IDENTITY]" in result.sanitized_text
    assert "[REDACTED_RESIDENTIAL_ADDRESS]" in result.sanitized_text
    assert "[REDACTED_FINANCIAL_INSTRUMENT]" in result.sanitized_text
    assert "Alice Wonderland" not in result.sanitized_text
    assert "742 Evergreen Terrace" not in result.sanitized_text
    assert "4532-1234-5678-9010" not in result.sanitized_text


def test_clean_memory_text_unaltered(manager: VerifiableProvenanceManager) -> None:
    """Verify that normal non-sensitive procedural instructions are untouched."""
    normal_text = "Prefers Python 3.12 with asyncio and pytest for automated validation."
    result = manager.inspect_memory_content(normal_text)
    assert result.intercepted is False
    assert result.has_child_privacy_violation is False
    assert result.sanitized_text == normal_text


def test_physical_purge_cascaded_sqlite_companion_files(
    manager: VerifiableProvenanceManager,
    temp_volume_root: Path,
) -> None:
    """Verify that SQLite companion files (-wal, -shm, -journal) are cascadedly overwritten and purged."""
    main_db = temp_volume_root / "app_memory.db"
    wal_file = temp_volume_root / "app_memory.db-wal"
    shm_file = temp_volume_root / "app_memory.db-shm"
    journal_file = temp_volume_root / "app_memory.db-journal"

    main_db.write_text("sqlite-primary-database-content-12345")
    wal_file.write_text("uncommitted-wal-log-record-67890")
    shm_file.write_text("index-shared-memory-cache-abcde")
    journal_file.write_text("rollback-journal-data-xyz")

    valid_token = manager.guard.generate_token("tenant-cascaded", "sb-wal-1", "vol-wal-1")
    ctx = TenantSandboxContext(
        tenant_id="tenant-cascaded",
        sandbox_id="sb-wal-1",
        volume_id="vol-wal-1",
        environment_token=valid_token,
    )

    receipt = manager.verify_and_purge_storage(main_db, ctx)
    assert receipt.status == PurgeVerificationStatus.VERIFIED_DESTROYED
    assert receipt.bytes_overwritten > 0

    assert not main_db.exists()
    assert not wal_file.exists()
    assert not shm_file.exists()
    assert not journal_file.exists()


def test_pre_ingest_pii_shield_chinese_patterns(manager: VerifiableProvenanceManager) -> None:
    """Verify pre-ingest interception of Chinese child identities, residential addresses, and ID cards."""
    zh_text = (
        "备忘录：我儿子叫张小明，家住：北京市海淀区中关村南大街1号院3号楼。 "
        "身份证号码：110108199003072345，银行卡号：6222020200112233。"
    )

    result = manager.inspect_memory_content(zh_text)
    assert result.intercepted is True
    assert result.has_child_privacy_violation is True
    assert PiiCategory.CHILD_IDENTITY in result.detected_categories
    assert PiiCategory.PRECISE_RESIDENTIAL_ADDRESS in result.detected_categories
    assert PiiCategory.FINANCIAL_INSTRUMENT in result.detected_categories
    assert PiiCategory.GOVERNMENT_ID in result.detected_categories

    assert "[REDACTED_CHILD_IDENTITY]" in result.sanitized_text
    assert "[REDACTED_RESIDENTIAL_ADDRESS]" in result.sanitized_text
    assert "[REDACTED_FINANCIAL_INSTRUMENT]" in result.sanitized_text
    assert "[REDACTED_GOVERNMENT_ID]" in result.sanitized_text
    assert "张小明" not in result.sanitized_text
    assert "中关村南大街1号院" not in result.sanitized_text
    assert "110108199003072345" not in result.sanitized_text
    assert "6222020200112233" not in result.sanitized_text


def test_fail_closed_guard_symlink_escape_confinement(
    manager: VerifiableProvenanceManager,
    temp_volume_root: Path,
) -> None:
    """Verify that a symlink pointing outside volume boundary is strictly caught and rejected."""
    import tempfile
    with tempfile.TemporaryDirectory() as outside_dir:
        outside_file = Path(outside_dir) / "sensitive_host.conf"
        outside_file.write_text("super-secret-host-config")

        symlink_inside = temp_volume_root / "link_to_outside.db"
        try:
            symlink_inside.symlink_to(outside_file)
        except OSError:
            pytest.skip("Symlink creation not permitted on this host environment")

        valid_token = manager.guard.generate_token("tenant-symlink", "sb-sym-1", "vol-sym-1")
        ctx = TenantSandboxContext(
            tenant_id="tenant-symlink",
            sandbox_id="sb-sym-1",
            volume_id="vol-sym-1",
            environment_token=valid_token,
        )

        with pytest.raises(FailClosedSecurityException) as exc_info:
            manager.verify_and_prove_residency(symlink_inside, ctx)
        assert "escapes sandbox volume boundary" in str(exc_info.value)

