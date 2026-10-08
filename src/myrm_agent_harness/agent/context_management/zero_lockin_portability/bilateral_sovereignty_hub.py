# [INPUT] UniversalArchivePayload, ArchivedSessionTree, HydratedUserProfile, IngestionResultReport, PortabilityHealthBadge from .portability_types
# [OUTPUT] BilateralSovereigntyArchiveHub, ZeroLockinUniversalContextPortabilitySuite
# [POS] Unified bilateral sovereignty hub providing end-to-end import, export, and portability health auditing

"""Bilateral sovereignty archive hub for zero-lockin context portability."""

from __future__ import annotations

import time

from .cross_platform_transcript_normalizer import CrossPlatformTranscriptNormalizer
from .offline_memory_hydration_engine import OfflineMemoryProfileHydrationEngine
from .portability_types import (
    ArchivedSessionTree,
    HydratedUserProfile,
    IngestionResultReport,
    PortabilityHealthBadge,
    SovereigntyRating,
    UniversalArchivePayload,
    ZeroLockinArchiveManifest,
)
from .universal_archive_spec import ARCHIVE_SPEC_VERSION, UniversalArchiveSpecEngine


class BilateralSovereigntyArchiveHub:
    """Unified engine for importing commercial exports and generating sovereign open archives."""

    @classmethod
    def ingest_external_archive(
        cls,
        raw_archive: str | bytes,
        user_id: str = "sovereign_user",
    ) -> tuple[UniversalArchivePayload, IngestionResultReport]:
        """Ingest external export archive, normalize session trees, and hydrate user profile."""
        start_time = time.perf_counter()
        sessions, platform, errors = CrossPlatformTranscriptNormalizer.normalize_archive(
            raw_archive
        )

        user_profile = OfflineMemoryProfileHydrationEngine.hydrate_profile(
            sessions=sessions,
            user_id=user_id,
        )

        message_count = sum(len(s.nodes) for s in sessions)
        checksum = UniversalArchiveSpecEngine.calculate_checksum(sessions, user_profile)

        manifest = ZeroLockinArchiveManifest(
            version=ARCHIVE_SPEC_VERSION,
            exported_platform=platform,
            export_timestamp=time.time(),
            session_count=len(sessions),
            message_count=message_count,
            entity_fact_count=len(user_profile.facts),
            checksum_sha256=checksum,
            description="Myrm Ingested Sovereign Archive",
        )

        payload = UniversalArchivePayload(
            manifest=manifest,
            sessions=sessions,
            user_profile=user_profile,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        report = IngestionResultReport(
            source_platform=platform,
            imported_sessions=len(sessions),
            imported_messages=message_count,
            extracted_facts=len(user_profile.facts),
            parse_errors=errors,
            processing_duration_ms=round(duration_ms, 2),
            success=(len(sessions) > 0 or len(errors) == 0),
        )

        return (payload, report)

    @classmethod
    def export_sovereign_archive(
        cls,
        sessions: list[ArchivedSessionTree],
        profile: HydratedUserProfile | None = None,
    ) -> tuple[str, UniversalArchivePayload]:
        """Bundle existing sessions and profile into an open-standard sovereign archive."""
        message_count = sum(len(s.nodes) for s in sessions)
        fact_count = len(profile.facts) if profile is not None else 0
        checksum = UniversalArchiveSpecEngine.calculate_checksum(sessions, profile)

        manifest = ZeroLockinArchiveManifest(
            version=ARCHIVE_SPEC_VERSION,
            exported_platform="universal_myrm",
            export_timestamp=time.time(),
            session_count=len(sessions),
            message_count=message_count,
            entity_fact_count=fact_count,
            checksum_sha256=checksum,
            description="Myrm Universal Zero-Lockin Export",
        )

        payload = UniversalArchivePayload(
            manifest=manifest,
            sessions=sessions,
            user_profile=profile,
        )

        serialized_json = UniversalArchiveSpecEngine.serialize_payload(payload)
        return (serialized_json, payload)

    @classmethod
    def assess_portability_health(
        cls, payload: UniversalArchivePayload
    ) -> PortabilityHealthBadge:
        """Audit the portability health and lock-in risk of a given archive payload."""
        score = 100
        warnings: list[str] = []

        # 1. Integrity check
        is_valid, integrity_errors = UniversalArchiveSpecEngine.verify_integrity(payload)
        if not is_valid:
            score -= 35
            warnings.extend(integrity_errors)

        # 2. Volume checks
        if len(payload.sessions) == 0:
            score -= 40
            warnings.append("Archive contains 0 conversational sessions.")

        total_msgs = sum(len(s.nodes) for s in payload.sessions)
        if total_msgs == 0:
            score -= 30
            warnings.append("Archive contains 0 messages across all sessions.")

        # 3. Memory hydration check
        if payload.user_profile is None or len(payload.user_profile.facts) == 0:
            score -= 15
            warnings.append(
                "No long-term memory facts or user profile hydrated; downstream agents will start amnesic."
            )

        score = max(0, min(100, score))

        rating: SovereigntyRating
        if score >= 85:
            rating = "FULL_SOVEREIGNTY"
        elif score >= 70:
            rating = "HIGH_PORTABILITY"
        elif score >= 50:
            rating = "DEGRADED_PORTABILITY"
        else:
            rating = "LOCKED_RISK"

        summary = (
            f"Portability Health Score: {score}/100 ({rating}). "
            f"Sessions: {len(payload.sessions)}, Messages: {total_msgs}, "
            f"Hydrated Facts: {len(payload.user_profile.facts) if payload.user_profile else 0}."
        )

        return PortabilityHealthBadge(
            portability_score=score,
            sovereignty_rating=rating,
            warnings=warnings,
            summary=summary,
        )


# Alias for unified naming convention
ZeroLockinUniversalContextPortabilitySuite = BilateralSovereigntyArchiveHub
