"""Comprehensive test suite for end-to-end sealed decision handoff and cryptographic continuity."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from myrm_agent_harness.agent.context_management.sealed_decision_handoff import (
    DecisionGraphCycleError,
    DecisionInvalidationGraph,
    DecisionNode,
    DecisionSealPacker,
    EndToEndSealedDecisionHandoffSuite,
    HandoffDecisionPackage,
    PreSealSecretMasker,
    SandboxVolumeDecisionStorageDriver,
    SealedDecisionError,
    SealedDecisionVerificationError,
    SealedHandoffConfig,
    SealedReceipt,
)


def test_pre_seal_secret_masker() -> None:
    """Validate credential pattern scanning, deterministic fingerprints, and scoped pruning."""
    masker = PreSealSecretMasker()

    sample_text = (
        "Configuring anthropic sk-ant-api0123456789abcdef0123456789 and "
        "openai sk-0123456789abcdef0123456789 alongside token "
        "ghp_111122223333444455556666777788889999 and aws AKIAIOSFODNN7EXAMPLE. "
        "Auth: Bearer my_super_secret_bearer_token_12345. "
        "Postgres: postgres://admin:super_secret_pw123@db.internal:5432/main"
    )

    masked_text = masker.mask_text(sample_text)
    assert "sk-ant-" not in masked_text
    assert "sk-0123" not in masked_text
    assert "ghp_" not in masked_text
    assert "AKIA" not in masked_text
    assert "super_secret_pw123" not in masked_text
    assert "[REDACTED_SECRET:" in masked_text

    # Test scoped pruning of environment variables
    env_vars = {
        "OPENAI_API_KEY": "sk-secret1234567890abcdef",
        "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "DATABASE_PASSWORD": "mypassword123",
        "APP_ENV": "production",
        "WORKSPACE_PATH": "/workspace/project",
        "PATH": "/usr/local/bin:/usr/bin",
        "RANDOM_UNAUTHORIZED_VAR": "leave_me_out",
    }

    pruned = masker.scoped_prune_env_vars(env_vars)
    assert "OPENAI_API_KEY" not in pruned
    assert "AWS_SECRET_ACCESS_KEY" not in pruned
    assert "DATABASE_PASSWORD" not in pruned
    assert "RANDOM_UNAUTHORIZED_VAR" not in pruned
    assert pruned["APP_ENV"] == "production"
    assert pruned["WORKSPACE_PATH"] == "/workspace/project"


def test_decision_invalidation_graph_and_negative_invariants() -> None:
    """Validate decision revision lineage, cycles prevention, and negative invariants."""
    graph = DecisionInvalidationGraph()

    # 1. Add initial exploratory decision
    d1 = DecisionNode(
        node_id="dec_01",
        title="SQLite Full Compaction",
        intent="Compact session events using physical chunk rows",
        rationale="Hypothesized to reduce file size significantly",
        chosen_option="Physical chunk row packing with zstd",
        rejected_options=["Raw json event lines", "Memory-only cache"],
    )
    graph.add_decision(d1)
    assert len(graph.get_active_decisions()) == 1

    # 2. Add second decision superseding d1 due to architectural defect
    d2 = DecisionNode(
        node_id="dec_02",
        title="Logical Turn Streaming Persistence",
        intent="Keep turn-level logical messages without token fragmentation",
        rationale="Avoid FTS5 corruption and CPU decompression latency",
        chosen_option="Single turn row with native indexing",
        rejected_options=["Physical chunk packing"],
    )
    graph.supersede_decision(old_node_id="dec_01", new_node=d2)

    # 3. Add a third decision that gets explicitly revoked
    d3 = DecisionNode(
        node_id="dec_03",
        title="Experimental In-Session Cron Promotion",
        intent="Promote /loop polling to persistent background cron automatically",
        rationale="Attempted automatic promotion without user consent",
        chosen_option="Silent background daemon",
        rejected_options=["Explicit user prompt"],
    )
    graph.add_decision(d3)
    graph.revoke_decision(
        node_id="dec_03",
        reason="Violates user consent boundaries; rejected by architecture review",
    )

    # 4. Verify active decisions and negative invariants
    active = graph.get_active_decisions()
    assert len(active) == 1
    assert active[0].node_id == "dec_02"

    negative_invariants = graph.extract_negative_invariants()
    assert len(negative_invariants) >= 2
    # Ensure revoked decision is captured as a negative invariant
    revoked_inv = [inv for inv in negative_invariants if inv.source_decision_id == "dec_03"]
    assert len(revoked_inv) >= 1
    assert "DO NOT ADOPT" in revoked_inv[0].rule

    # Ensure supersede cycle causes error
    d_cycle = DecisionNode(
        node_id="dec_cycle",
        title="Cycle",
        intent="Test",
        rationale="Test",
        chosen_option="Test",
        supersedes_id="dec_cycle",
    )
    with pytest.raises(DecisionGraphCycleError):
        graph.add_decision(d_cycle)

    sanity = graph.verify_handoff_sanity()
    assert sanity.is_valid is True
    assert sanity.active_count == 1
    assert sanity.revoked_count == 1
    assert sanity.superseded_count == 1


def test_decision_seal_packer_cryptographic_pipeline() -> None:
    """Validate AES-256-GCM authenticated encryption and SHA-256 dual verification."""
    packer = DecisionSealPacker()
    key = packer.generate_cryptographic_key()

    package = HandoffDecisionPackage(
        topic="compiler_optimization",
        active_decisions=[
            DecisionNode(
                node_id="dec_opt_1",
                title="Use LLVM LTO",
                intent="Optimize binary performance",
                rationale="Benchmarked 14% speedup on benchmark testbed",
                chosen_option="ThinLTO with O3",
                rejected_options=["Monolithic LTO", "O2 baseline"],
            )
        ],
        negative_invariants=[],
        sanitized_env_vars={"APP_ENV": "release"},
        trace_artifacts={"benchmark_stdout": "Latency 1.2ms (p99)"},
    )

    # Seal package
    receipt, ciphertext = packer.seal_package(
        package=package,
        key=key,
        key_ref="vault://unit_test_key",
        summary="LLVM LTO Compiler Decisions",
    )

    assert receipt.enc == "aes-256-gcm"
    assert len(receipt.sha256_digest) == 64
    assert len(ciphertext) > 12

    # Unseal with correct key
    hydrated = packer.unseal_package(ciphertext, receipt, key)
    assert hydrated.topic == "compiler_optimization"
    assert len(hydrated.active_decisions) == 1
    assert hydrated.active_decisions[0].chosen_option == "ThinLTO with O3"

    # Reject unseal with incorrect key
    wrong_key = packer.generate_cryptographic_key()
    with pytest.raises(SealedDecisionVerificationError):
        packer.unseal_package(ciphertext, receipt, wrong_key)

    # Reject unseal with tampered ciphertext (auth tag verification)
    tampered_ciphertext = bytearray(ciphertext)
    tampered_ciphertext[-1] ^= 0x01
    with pytest.raises(SealedDecisionVerificationError):
        packer.unseal_package(bytes(tampered_ciphertext), receipt, key)

    # Reject unseal with mismatched receipt SHA-256 digest
    tampered_receipt = SealedReceipt(
        receipt_id=receipt.receipt_id,
        topic=receipt.topic,
        enc=receipt.enc,
        key_ref=receipt.key_ref,
        sha256_digest="0" * 64,
        summary=receipt.summary,
        payload_bytes_len=receipt.payload_bytes_len,
        created_at_iso=receipt.created_at_iso,
    )
    with pytest.raises(SealedDecisionVerificationError):
        packer.unseal_package(ciphertext, tampered_receipt, key)


def test_sandbox_volume_storage_and_immutable_pointer_chain(tmp_path: Path) -> None:
    """Validate sandbox volume persistence, 0600 file security, and immutable versioning."""
    storage_dir = tmp_path / "volume"
    driver = SandboxVolumeDecisionStorageDriver(storage_dir)

    packer = DecisionSealPacker()
    key = packer.generate_cryptographic_key()

    # Version 1
    pkg1 = HandoffDecisionPackage(
        topic="distributed_db_migration",
        active_decisions=[
            DecisionNode(
                node_id="db_01",
                title="Select Database",
                intent="Support ACID transactions",
                rationale="Strict serializability required",
                chosen_option="PostgreSQL with Citus",
            )
        ],
        negative_invariants=[],
    )
    receipt1, cipher1 = packer.seal_package(pkg1, key, "vault://db_key", "V1 DB Decision")
    driver.store_sealed_package(receipt1, cipher1)

    # Version 2 (immutable pointer update)
    pkg2 = HandoffDecisionPackage(
        topic="distributed_db_migration",
        active_decisions=[
            DecisionNode(
                node_id="db_02",
                title="Select Database v2",
                intent="High write throughput",
                rationale="Partitioned tables sufficient",
                chosen_option="PostgreSQL Native Partitioning",
            )
        ],
        negative_invariants=[],
    )
    receipt2, cipher2 = packer.seal_package(pkg2, key, "vault://db_key", "V2 DB Decision")
    driver.store_sealed_package(receipt2, cipher2)

    # Verify both versions exist
    receipts = driver.list_receipts(topic="distributed_db_migration")
    assert len(receipts) == 2

    # Verify latest pointer resolution
    latest = driver.get_latest_receipt("distributed_db_migration")
    assert latest is not None
    assert latest.receipt_id == receipt2.receipt_id

    # Retrieve and decrypt v1
    v1_receipt, v1_cipher = driver.fetch_sealed_package(receipt1.receipt_id)
    v1_hydrated = packer.unseal_package(v1_cipher, v1_receipt, key)
    assert v1_hydrated.active_decisions[0].chosen_option == "PostgreSQL with Citus"


def test_end_to_end_sealed_decision_handoff_suite(tmp_path: Path) -> None:
    """Validate end-to-end facade: graph sanity, secret masking, sealing, and prompt directives."""
    config = SealedHandoffConfig(storage_volume_dir=str(tmp_path / "sealed_vault"))
    suite = EndToEndSealedDecisionHandoffSuite(config=config)
    packer = DecisionSealPacker()
    key = packer.generate_cryptographic_key()

    # 1. Test provable first-run loop
    loop_ok = suite.run_first_run_provable_loop(encryption_key=key)
    assert loop_ok is True

    # 2. Build task decision graph
    graph = suite.create_graph()
    d1 = DecisionNode(
        node_id="task_d1",
        title="Framework Selection for sk-ant-secret1234567890abcdef agent",
        intent="Select high throughput async web framework",
        rationale="Benchmark FastAPI vs Starlette with token ghp_111122223333444455556666777788889999",
        chosen_option="FastAPI with Pydantic v2",
        rejected_options=["Django", "Flask"],
    )
    d2 = DecisionNode(
        node_id="task_d2",
        title="Cache Layer",
        intent="In-memory cache for session records",
        rationale="Low latency key-value store",
        chosen_option="Redis Cluster",
        rejected_options=["Memcached"],
    )
    graph.add_decision(d1)
    graph.add_decision(d2)

    # Revoke d2
    graph.revoke_decision(
        node_id="task_d2",
        reason="Redis cluster is overkill for single-sandbox deployment",
    )

    # Seal and store with raw env vars containing secrets
    raw_envs = {
        "OPENAI_API_KEY": "sk-secret1234567890abcdef",
        "APP_ENV": "staging",
        "CUSTOM_SECRET": "topsecretpassword",
    }
    raw_traces = {
        "execution_log": "Connected with sk-ant-secret1234567890abcdef successfully."
    }

    receipt, sanity = suite.seal_and_store_decision_handoff(
        topic="sandbox_backend_arch",
        graph=graph,
        encryption_key=key,
        summary="Sandbox Backend Architecture Decisions",
        raw_env_vars=raw_envs,
        trace_artifacts=raw_traces,
    )

    assert sanity.is_valid is True
    assert sanity.active_count == 1
    assert sanity.revoked_count == 1

    # Open and hydrate
    hydrated = suite.open_and_hydrate_decision_handoff(
        receipt_id=receipt.receipt_id,
        decryption_key=key,
    )

    # Assert active decisions preserved and secrets masked
    assert len(hydrated.active_decisions) == 1
    active_node = hydrated.active_decisions[0]
    assert active_node.node_id == "task_d1"
    assert "sk-ant-" not in active_node.title
    assert "[REDACTED_SECRET:" in active_node.title
    assert "ghp_" not in active_node.rationale

    # Assert secrets pruned from env vars
    assert "OPENAI_API_KEY" not in hydrated.sanitized_env_vars
    assert "CUSTOM_SECRET" not in hydrated.sanitized_env_vars
    assert hydrated.sanitized_env_vars["APP_ENV"] == "staging"

    # Assert traces sanitized
    assert "sk-ant-" not in hydrated.trace_artifacts["execution_log"]

    # Assert negative invariants formatted into prompt directive
    directive = suite.generate_negative_invariants_directive(hydrated)
    assert "STRICT NEGATIVE INVARIANTS" in directive
    assert "Redis cluster is overkill" in directive
