"""[INPUT] Multimodal media assets, 3-step diagnostic traces, and Golden Eval requests.
[OUTPUT] Unit tests verifying decoupled media references, 4-state lifecycle, and eval sample pinning.
[POS] myrm-agent-harness/tests/observability/test_multimodal_trace.py
"""

from myrm_agent_harness.observability.multimodal_trace import (
    MediaModality,
    MediaReference,
    MediaVisibilityState,
    MultimodalMessagePart,
    MultimodalStepType,
    MultimodalTraceManager,
    MultimodalTraceRecord,
    MultimodalTraceStep,
)


def test_media_reference_registration_and_decoupling() -> None:
    """Verifies that media reference holds lightweight metadata rather than raw Base64 payload."""
    manager = MultimodalTraceManager()
    ref = manager.register_media(
        media_id="med_001",
        uri="storage://workspace/screenshots/login_screen.png",
        modality=MediaModality.IMAGE,
        mime_type="image/png",
        file_size_bytes=1048576,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        presigned_preview_url="https://preview.local/media/med_001?sig=test",
    )

    assert ref.media_id == "med_001"
    assert ref.modality == MediaModality.IMAGE
    assert ref.visibility_state == MediaVisibilityState.READY
    assert ref.file_size_bytes == 1048576
    assert ref.sha256_hash.startswith("e3b0c442")

    # Verify OTel message part compatibility
    part = MultimodalMessagePart(part_type="media_reference", media_ref=ref)
    p_dict = part.to_dict()
    assert p_dict["part_type"] == "media_reference"
    assert p_dict["media_ref"] is not None


def test_media_visibility_lifecycle_and_trace_sync() -> None:
    """Verifies 4-state visibility transitions and trace synchronization."""
    manager = MultimodalTraceManager()

    # 1. Register media
    manager.register_media(
        media_id="med_002",
        uri="storage://audio/prompt_voice.wav",
        modality="audio",
        mime_type="audio/wav",
        file_size_bytes=524288,
        sha256_hash="abc123hash",
    )

    # 2. Record trace referencing media
    trace = manager.record_trace(
        trace_id="tr_100",
        session_id="sess_audio",
        prompt_summary="Voice command execution",
        media_ids=["med_002"],
    )
    assert len(trace.media_references) == 1
    assert trace.media_references[0].visibility_state == MediaVisibilityState.READY

    # 3. Transition to EXPIRED
    ok = manager.update_media_visibility(
        media_id="med_002",
        visibility_state=MediaVisibilityState.EXPIRED,
        presigned_preview_url="https://preview.local/refresh_needed",
    )
    assert ok is True

    # 4. Verify updated state in trace
    updated_trace = manager.get_trace("tr_100")
    assert updated_trace is not None
    assert updated_trace.media_references[0].visibility_state == MediaVisibilityState.EXPIRED
    assert updated_trace.media_references[0].presigned_preview_url == "https://preview.local/refresh_needed"


def test_3step_inspection_and_golden_eval_pinning() -> None:
    """Verifies Input-Execution-Feedback 3-step inspector and Golden Eval sample lock."""
    manager = MultimodalTraceManager()

    # Setup media
    manager.register_media(
        media_id="shot_input",
        uri="storage://screenshots/bug.png",
        modality=MediaModality.IMAGE,
        mime_type="image/png",
        file_size_bytes=204800,
        sha256_hash="hash_shot_input",
    )

    # Build 3 diagnostic steps
    steps = [
        MultimodalTraceStep(
            step_index=1,
            step_type=MultimodalStepType.INPUT,
            description="User attached login form overflow screenshot",
            media_ids=("shot_input",),
        ),
        MultimodalTraceStep(
            step_index=2,
            step_type=MultimodalStepType.EXECUTION,
            description="Agent inspected DOM and applied CSS overflow-y auto fix",
            status="success",
        ),
        MultimodalTraceStep(
            step_index=3,
            step_type=MultimodalStepType.FEEDBACK,
            description="Visual regression passed; user approved pull request",
            status="success",
        ),
    ]

    trace = manager.record_trace(
        trace_id="tr_golden_01",
        session_id="sess_fix_css",
        prompt_summary="Fix CSS overflow on login",
        media_ids=["shot_input"],
        steps=steps,
    )
    assert len(trace.steps) == 3
    assert trace.steps[0].step_type == MultimodalStepType.INPUT
    assert trace.pinned_for_golden_eval is False

    # Pin for Golden Eval
    pin_ok = manager.pin_trace_for_golden_eval(
        trace_id="tr_golden_01",
        category="ui_layout_regression",
    )
    assert pin_ok is True

    pinned_trace = manager.get_trace("tr_golden_01")
    assert pinned_trace is not None
    assert pinned_trace.pinned_for_golden_eval is True
    assert pinned_trace.golden_eval_category == "ui_layout_regression"

    # Filter queries
    pinned_list = manager.list_traces(pinned_only=True)
    assert len(pinned_list) == 1
    assert pinned_list[0].trace_id == "tr_golden_01"

    image_list = manager.list_traces(modality=MediaModality.IMAGE)
    assert len(image_list) == 1


def test_manager_reset() -> None:
    """Verifies that reset clears all registered media and traces."""
    manager = MultimodalTraceManager()
    manager.register_media(
        media_id="m_temp",
        uri="storage://test.png",
        modality=MediaModality.IMAGE,
        mime_type="image/png",
        file_size_bytes=100,
        sha256_hash="hash",
    )
    manager.record_trace("tr_tmp", "sess_tmp", "Summary", media_ids=["m_temp"])

    assert len(manager.list_traces()) == 1
    manager.reset()
    assert len(manager.list_traces()) == 0
    assert manager.get_media_reference("m_temp") is None
