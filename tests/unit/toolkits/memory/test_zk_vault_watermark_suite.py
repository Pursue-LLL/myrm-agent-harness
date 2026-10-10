"""Unit tests for Zero Knowledge Memory Vault and Provenance Watermarking (Item 159).

[INPUT]
- Passphrases, mock memories with sensitivity tiers, simulated sandbox environments.

[OUTPUT]
- Asserts verifying envelope encryption, invisible watermark extraction, distillation, and anti-cloning.

[POS]
- Harness test suite for Item 159 ZeroKnowledgeMemoryVaultAndAntiCloningProvenanceWatermarkingSuite.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.zk_vault_watermark import (
    DistilledMemoryItem,
    EnvelopeCryptoEngine,
    InvisibleWatermarkEngine,
    SandboxAntiCloningGate,
    SensitivityDistillationExporter,
    ZeroKnowledgeMemoryVaultManager,
)


def test_envelope_crypto_roundtrip_and_wrong_passphrase() -> None:
    crypto = EnvelopeCryptoEngine(pbkdf2_iterations=10_000)
    passphrase = "master_super_secret_pwd_99"
    plaintext = "Confidential business strategy: adopt sqlite-vec for zero daemon memory"

    # 1. Encrypt payload
    envelope = crypto.encrypt_payload(plaintext, passphrase=passphrase)
    assert envelope.ciphertext_hex != ""
    assert envelope.salt_hex != ""
    assert envelope.encrypted_dek_hex != ""

    # 2. Decrypt with correct passphrase
    decrypted = crypto.decrypt_payload(envelope, passphrase=passphrase)
    assert decrypted == plaintext

    # 3. Decrypt with wrong passphrase -> raise ValueError
    with pytest.raises(ValueError, match="Decryption failed"):
        crypto.decrypt_payload(envelope, passphrase="wrong_passphrase_000")


def test_invisible_watermark_embed_and_extract() -> None:
    engine = InvisibleWatermarkEngine()
    source_text = "Standard operating procedure for deploying to AWS us-east-1."
    tenant_id = "tenant_alpha_01"
    user_id = "user_dev_99"
    now_iso = "2026-10-10T12:00:00Z"

    # 1. Embed watermark
    watermarked, watermark = engine.embed_watermark(
        source_text,
        tenant_id=tenant_id,
        user_id=user_id,
        timestamp_iso=now_iso,
    )
    assert watermarked != source_text
    assert "\u200D" in watermarked
    assert watermark.signature != ""

    # 2. Extract and verify watermark
    extracted = engine.extract_watermark(watermarked)
    assert extracted is not None
    assert extracted.tenant_id == tenant_id
    assert extracted.user_id == user_id
    assert extracted.timestamp_iso == now_iso
    assert extracted.signature == watermark.signature

    # 3. Clean text without watermark returns None
    assert engine.extract_watermark("Plain text without any zero width symbols") is None


def test_sensitivity_tiering_and_pii_redaction() -> None:
    distiller = SensitivityDistillationExporter()

    items = [
        DistilledMemoryItem(
            memory_id="mem_pub_01",
            content="Use TypeScript strict mode across packages",
            sensitivity_tier="public_sharable",
            category="coding",
        ),
        DistilledMemoryItem(
            memory_id="mem_team_02",
            content="Contact lead engineer at dev@corp.example.com with api_key: secret_12345678",
            sensitivity_tier="team_internal",
            category="workflow",
        ),
        DistilledMemoryItem(
            memory_id="mem_priv_03",
            content="Personal bank balance and PIN code 9876",
            sensitivity_tier="strictly_private_pii",
            category="personal",
        ),
    ]

    # 1. Public export: private and team items excluded
    pub_distilled = distiller.distill_memories(items, target_tier="public_sharable")
    assert len(pub_distilled) == 1
    assert pub_distilled[0].memory_id == "mem_pub_01"

    # 2. Team export: private items excluded, team internal PII redacted
    team_distilled = distiller.distill_memories(
        items, target_tier="team_internal", redact_pii=True
    )
    assert len(team_distilled) == 2
    team_item = next(it for it in team_distilled if it.memory_id == "mem_team_02")
    assert "[REDACTED_EMAIL]" in team_item.content
    assert "[REDACTED_SECRET]" in team_item.content
    assert team_item.redacted is True


def test_sandbox_anti_cloning_gate() -> None:
    gate = SandboxAntiCloningGate()

    # 1. Initial binding established
    ok, msg = gate.verify_environment(
        current_instance_guid="inst_sbx_001",
        current_volume_id="vol_ssd_100",
        current_tenant_id="tenant_corp_01",
    )
    assert ok is True
    assert gate.current_binding is not None

    # 2. Verify legitimate environment
    ok_same, _ = gate.verify_environment(
        current_instance_guid="inst_sbx_001",
        current_volume_id="vol_ssd_100",
        current_tenant_id="tenant_corp_01",
    )
    assert ok_same is True

    # 3. Detect unauthorized cloning (foreign machine GUID) -> locked
    ok_clone, alert = gate.verify_environment(
        current_instance_guid="inst_rogue_999",
        current_volume_id="vol_ssd_100",
        current_tenant_id="tenant_corp_01",
    )
    assert ok_clone is False
    assert "CRITICAL SECURITY ALERT" in alert
    assert gate.current_binding.is_locked is True

    # Subsequent access locked
    ok_locked, lock_msg = gate.verify_environment(
        current_instance_guid="inst_sbx_001",
        current_volume_id="vol_ssd_100",
        current_tenant_id="tenant_corp_01",
    )
    assert ok_locked is False
    assert "LOCKED" in lock_msg

    # 4. Unlock with admin passphrase and rebind
    unlocked = gate.unlock_and_rebind(
        provided_passphrase="admin_valid_token",
        expected_passphrase="admin_valid_token",
        new_instance_guid="inst_migrated_002",
        new_volume_id="vol_ssd_100",
        tenant_id="tenant_corp_01",
    )
    assert unlocked is True
    assert gate.current_binding.is_locked is False
    assert gate.current_binding.instance_guid == "inst_migrated_002"


def test_zk_vault_manager_end_to_end_export() -> None:
    manager = ZeroKnowledgeMemoryVaultManager()
    passphrase = "test_vault_passphrase_321"

    # 1. Seal memories with master passphrase
    manager.seal_and_store_memory(
        memory_id="mem_rule_01",
        content="Always write comprehensive unit tests",
        sensitivity_tier="public_sharable",
        category="rules",
        passphrase=passphrase,
    )
    manager.seal_and_store_memory(
        memory_id="mem_rule_02",
        content="Internal deploy pipeline credentials token: abc_xyz_987654321",
        sensitivity_tier="team_internal",
        category="deploy",
        passphrase=passphrase,
    )

    # 2. Unseal memory
    unsealed = manager.unseal_memory("mem_rule_01", passphrase=passphrase)
    assert unsealed.content == "Always write comprehensive unit tests"

    # 3. Export distilled package with invisible watermark
    pkg = manager.export_distilled_package(
        tenant_id="tenant_gamma",
        user_id="user_admin",
        target_tier="team_internal",
        redact_pii=True,
    )
    assert len(pkg.items) == 2
    assert pkg.watermark_signature != ""
    assert "[REDACTED_SECRET]" in pkg.watermarked_text

    # 4. Reverse extraction of provenance watermark
    verified_watermark = manager.verify_exported_watermark(pkg.watermarked_text)
    assert verified_watermark is not None
    assert verified_watermark.tenant_id == "tenant_gamma"
    assert verified_watermark.user_id == "user_admin"
    assert verified_watermark.signature == pkg.watermark_signature
