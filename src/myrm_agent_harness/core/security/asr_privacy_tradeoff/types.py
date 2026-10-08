"""Domain types for ASR Privacy Tradeoff (Audio Deletion vs Speaker Profiling).

[INPUT]
- Audio transcription job settings and retention policies.

[OUTPUT]
- AudioRetentionPolicy, SpeakerProfileCapability, AsrPrivacyDecision, AudioTranscriptionJob.

[POS]
Domain models representing acoustic privacy guarantees and capability tradeoffs.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class AudioRetentionPolicy(StrEnum):
    """Retention policy for recorded voice audio."""

    EPHEMERAL_TRANSCRIPT_ONLY = (
        "ephemeral_transcript_only"  # Default: Delete audio immediately after ASR
    )
    RETAIN_VOICE_EMBEDDINGS_ONLY = (
        "retain_voice_embeddings_only"  # Delete raw audio, keep speaker vector
    )
    FULL_PERSISTENCE = "full_persistence"  # Keep raw audio and voice profile


class SpeakerProfileCapability(StrEnum):
    """Speaker profiling capability degradation state."""

    DISABLED_NO_SPEAKER_DATA = "disabled_no_speaker_data"
    EMBEDDINGS_ONLY = "embeddings_only"
    FULL_DIARIZATION_AND_PLAYBACK = "full_diarization_and_playback"


@dataclass(frozen=True)
class AsrPrivacyDecision:
    """Decision and impact outcome for ASR audio handling."""

    retention_policy: AudioRetentionPolicy
    raw_audio_purged: bool
    speaker_capability: SpeakerProfileCapability
    privacy_disclosure_confirmed: bool
    tradeoff_warning: str | None
    explanation: str


@dataclass(frozen=True)
class AudioTranscriptionJob:
    """ASR transcription job descriptor."""

    job_id: str
    audio_bytes_length: int
    retention_policy: AudioRetentionPolicy = (
        AudioRetentionPolicy.EPHEMERAL_TRANSCRIPT_ONLY
    )
    consent_given: bool = True
