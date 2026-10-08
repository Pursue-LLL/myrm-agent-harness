"""Unit tests for ASR Privacy Tradeoff suite."""

import pytest

from myrm_agent_harness.core.security.asr_privacy_tradeoff import (
    AsrPrivacyTradeoffController,
    AudioRetentionPolicy,
    AudioTranscriptionJob,
    SpeakerProfileCapability,
)


def test_ephemeral_transcript_only_default_privacy() -> None:
    job = AudioTranscriptionJob(
        job_id="job-101",
        audio_bytes_length=102400,
        retention_policy=AudioRetentionPolicy.EPHEMERAL_TRANSCRIPT_ONLY,
    )

    decision = AsrPrivacyTradeoffController.process_transcription_cleanup(job)

    assert decision.raw_audio_purged is True
    assert (
        decision.speaker_capability == SpeakerProfileCapability.DISABLED_NO_SPEAKER_DATA
    )
    assert decision.privacy_disclosure_confirmed is True
    assert "Raw audio is destroyed immediately" in decision.tradeoff_warning
    assert "Zero acoustic retention guarantee" in decision.explanation


def test_retain_voice_embeddings_only() -> None:
    decision = AsrPrivacyTradeoffController.evaluate_policy(
        AudioRetentionPolicy.RETAIN_VOICE_EMBEDDINGS_ONLY,
        user_confirmed=True,
    )

    assert decision.raw_audio_purged is True
    assert decision.speaker_capability == SpeakerProfileCapability.EMBEDDINGS_ONLY
    assert (
        "Raw recording is destroyed, but mathematical speaker embeddings"
        in decision.tradeoff_warning
    )


def test_full_persistence_tradeoff_warning() -> None:
    decision = AsrPrivacyTradeoffController.evaluate_policy(
        AudioRetentionPolicy.FULL_PERSISTENCE,
        user_confirmed=False,
    )

    assert decision.raw_audio_purged is False
    assert (
        decision.speaker_capability
        == SpeakerProfileCapability.FULL_DIARIZATION_AND_PLAYBACK
    )
    assert decision.privacy_disclosure_confirmed is False
    assert "Full Acoustic Retention" in decision.tradeoff_warning
