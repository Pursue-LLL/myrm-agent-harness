"""ASR privacy tradeoff policy controller.

[INPUT]
- AudioRetentionPolicy and user confirmation state.

[OUTPUT]
- AsrPrivacyDecision: Explicit privacy guarantees and degraded speaker identification capability.

[POS]
Core controller enforcing transparent tradeoffs between acoustic audio destruction and speaker profiling.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.asr_privacy_tradeoff.types import (
    AsrPrivacyDecision,
    AudioRetentionPolicy,
    AudioTranscriptionJob,
    SpeakerProfileCapability,
)


class AsrPrivacyTradeoffController:
    """Controls ASR lifecycle, zero-retention audio shredding, and speaker capability degradation."""

    @classmethod
    def evaluate_policy(
        cls,
        policy: AudioRetentionPolicy,
        user_confirmed: bool = True,
    ) -> AsrPrivacyDecision:
        """Evaluate privacy and capability impact of selected retention policy."""
        if policy == AudioRetentionPolicy.EPHEMERAL_TRANSCRIPT_ONLY:
            return AsrPrivacyDecision(
                retention_policy=policy,
                raw_audio_purged=True,
                speaker_capability=SpeakerProfileCapability.DISABLED_NO_SPEAKER_DATA,
                privacy_disclosure_confirmed=user_confirmed,
                tradeoff_warning=(
                    "Privacy First: Raw audio is destroyed immediately upon transcription. "
                    "Speaker biometric profiles cannot be generated, refined, or matched across sessions."
                ),
                explanation="Zero acoustic retention guarantee. Privacy priority for wearer and bystanders.",
            )

        if policy == AudioRetentionPolicy.RETAIN_VOICE_EMBEDDINGS_ONLY:
            return AsrPrivacyDecision(
                retention_policy=policy,
                raw_audio_purged=True,
                speaker_capability=SpeakerProfileCapability.EMBEDDINGS_ONLY,
                privacy_disclosure_confirmed=user_confirmed,
                tradeoff_warning=(
                    "Anonymized Audio: Raw recording is destroyed, but mathematical speaker embeddings are retained "
                    "for diarization. Audio playback is impossible."
                ),
                explanation="Mathematical feature extraction retained without keeping reconstructible acoustic waves.",
            )

        # Full persistence
        return AsrPrivacyDecision(
            retention_policy=policy,
            raw_audio_purged=False,
            speaker_capability=SpeakerProfileCapability.FULL_DIARIZATION_AND_PLAYBACK,
            privacy_disclosure_confirmed=user_confirmed,
            tradeoff_warning=(
                "Full Acoustic Retention: Raw audio is stored. Poses surveillance risk to wearers and "
                "bystanders without implicit consent."
            ),
            explanation="Maximum capability retained with highest privacy exposure risk.",
        )

    @classmethod
    def process_transcription_cleanup(
        cls, job: AudioTranscriptionJob
    ) -> AsrPrivacyDecision:
        """Execute post-transcription data lifecycle enforcement."""
        decision = cls.evaluate_policy(
            job.retention_policy,
            user_confirmed=job.consent_given,
        )
        return decision
