"""Unit tests for local-to-cloud task hot handoff and input consistency verification suite.

Verifies:
- Streaming chunked SHA-256 calculation and fast-path size mismatch short-circuiting.
- Incremental workspace delta calculation, zip bundling, and extraction.
- End-to-end task evacuation from local desktop to remote cloud sandbox.
- Input material cryptographic verification and tamper rejection.
- Offline cloud relay execution and reverse recall back to local workspace.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.runtime.hot_handoff import (
    ExecutionEnvironment,
    HandoffPhase,
    HotHandoffCoordinator,
    MaterialIntegrityGuard,
    WorkspaceDeltaSyncer,
)


def test_material_integrity_guard_chunked_sha256() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        test_file = root / "raw_video_footage.mp4"
        test_file.write_bytes(b"sample video frame data 0123456789" * 100)

        digest = MaterialIntegrityGuard.compute_file_digest(test_file, relative_to=root)
        assert digest.relative_path == "raw_video_footage.mp4"
        assert digest.size_bytes == 3400
        assert len(digest.sha256_hash) == 64

        # Verify against self -> ok
        ok, err = MaterialIntegrityGuard.verify_single_material(digest, test_file)
        assert ok is True
        assert err is None

        # Verify against truncated file -> fast-path size mismatch
        truncated_file = root / "corrupted.mp4"
        truncated_file.write_bytes(b"short")
        ok_trunc, err_trunc = MaterialIntegrityGuard.verify_single_material(digest, truncated_file)
        assert ok_trunc is False
        assert "Byte size mismatch" in str(err_trunc)

        # Verify against same-size but altered content -> SHA-256 mismatch
        tampered_file = root / "tampered.mp4"
        tampered_file.write_bytes(b"x" * 3400)
        ok_tamp, err_tamp = MaterialIntegrityGuard.verify_single_material(digest, tampered_file)
        assert ok_tamp is False
        assert "SHA-256 digest mismatch" in str(err_tamp)


def test_workspace_delta_syncer_scan_pack_and_apply() -> None:
    with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as tgt_dir:
        src = Path(src_dir)
        tgt = Path(tgt_dir)

        # Create nested workspace structure
        (src / "sub").mkdir()
        (src / "sub" / "a.py").write_text("print('hello')", encoding="utf-8")
        (src / "config.json").write_text('{"mode": "batch"}', encoding="utf-8")

        # Compute delta
        delta = WorkspaceDeltaSyncer.compute_delta(src)
        assert len(delta) == 2
        assert "config.json" in delta
        assert "sub/a.py" in delta

        # Export bundle and apply to target
        bundle = WorkspaceDeltaSyncer.export_delta_bundle(src, delta)
        files_extracted, bytes_written = WorkspaceDeltaSyncer.apply_delta_bundle(tgt, bundle)

        assert files_extracted == 2
        assert bytes_written > 0
        assert (tgt / "sub" / "a.py").read_text(encoding="utf-8") == "print('hello')"
        assert (tgt / "config.json").read_text(encoding="utf-8") == '{"mode": "batch"}'


def test_hot_handoff_coordinator_successful_evacuation_and_cloud_relay() -> None:
    with tempfile.TemporaryDirectory() as loc_dir, tempfile.TemporaryDirectory() as cloud_dir:
        loc = Path(loc_dir)
        cloud = Path(cloud_dir)

        # 1. Local setup: script and critical input dataset
        dataset_file = loc / "input_dataset.csv"
        dataset_file.write_text("id,label\n1,pos\n2,neg\n", encoding="utf-8")
        (loc / "pipeline.py").write_text("# running step 4", encoding="utf-8")

        coordinator = HotHandoffCoordinator()

        # 2. Local evacuation to cloud
        payload, delta_bundle = coordinator.evacuate_to_cloud(
            task_id="task_large_etl_42",
            session_id="sess_etl",
            current_step=4,
            state_vector={"processed_rows": 1000, "status": "checkpointed"},
            local_workspace=loc,
            critical_materials=(dataset_file,),
        )

        assert payload.origin_env == ExecutionEnvironment.LOCAL_DESKTOP
        assert payload.target_env == ExecutionEnvironment.CLOUD_SANDBOX
        assert payload.frozen_step_index == 4
        assert len(payload.materials) == 1
        assert payload.materials[0].relative_path == "input_dataset.csv"

        # 3. Cloud reception & material verification
        # The delta bundle extracts the dataset into cloud workspace
        receipt = coordinator.receive_and_verify_cloud_handoff(
            payload=payload,
            cloud_workspace=cloud,
            delta_bundle=delta_bundle,
        )

        assert receipt.is_success is True
        assert receipt.phase == HandoffPhase.CLOUD_RUNNING
        assert receipt.material_consistency_passed is True
        assert receipt.active_env == ExecutionEnvironment.CLOUD_SANDBOX

        # 4. Cloud executes and generates an output artifact
        (cloud / "output_cleaned.parquet").write_bytes(b"PAR1_MOCK_PROCESSED_DATA")

        # 5. Recall completed output back to local workspace
        recall_receipt = coordinator.recall_to_local(
            handoff_id=payload.handoff_id,
            task_id=payload.task_id,
            cloud_workspace=cloud,
            local_workspace=loc,
        )

        assert recall_receipt.is_success is True
        assert recall_receipt.phase == HandoffPhase.COMPLETED
        assert recall_receipt.active_env == ExecutionEnvironment.LOCAL_DESKTOP
        # Check that local now has the cloud-generated file
        assert (loc / "output_cleaned.parquet").is_file()
        assert (loc / "output_cleaned.parquet").read_bytes() == b"PAR1_MOCK_PROCESSED_DATA"


def test_hot_handoff_coordinator_material_mismatch_aborts_relay() -> None:
    with tempfile.TemporaryDirectory() as loc_dir, tempfile.TemporaryDirectory() as cloud_dir:
        loc = Path(loc_dir)
        cloud = Path(cloud_dir)

        # Local creates video material
        video_local = loc / "source_film.mkv"
        video_local.write_bytes(b"ORIGINAL_FILM_PAYLOAD_1080P")

        coordinator = HotHandoffCoordinator()

        payload, _ = coordinator.evacuate_to_cloud(
            task_id="task_video_edit",
            session_id="sess_vid",
            current_step=12,
            state_vector={"frame": 1200},
            local_workspace=loc,
            critical_materials=(video_local,),
        )

        # In cloud workspace, the video file was uploaded but corrupted / different version
        (cloud / "source_film.mkv").write_bytes(b"DIFFERENT_VERSION_720P_CORRUPTED")

        # Attempt to receive handoff without overwriting the corrupted cloud video
        receipt = coordinator.receive_and_verify_cloud_handoff(
            payload=payload,
            cloud_workspace=cloud,
            delta_bundle=None,  # Do not overwrite, simulate pre-existing remote asset
        )

        assert receipt.is_success is False
        assert receipt.phase == HandoffPhase.FAILED
        assert receipt.material_consistency_passed is False
        assert "Material verification failed" in str(receipt.error_message)
        assert "mismatch" in str(receipt.error_message).lower()
