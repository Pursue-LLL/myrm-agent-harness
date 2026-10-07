"""Persona and venture affinity profile builder.

Aggregates developer identity, active project matrices, technical stacks,
and negative bias filters from long-term memory into a compact profile.

[INPUT]
- toolkits.memory.social_curator.models::UserAffinityProfile (POS: Data models for
  HighSignalSocialFeedCurator.)

[OUTPUT]
- UserAffinityProfileBuilder: Compiles unstructured memory entries and explicit attributes into
  UserAffinityProfile.

[POS]
Persona and venture affinity profile builder.
"""

from collections.abc import Mapping

from .models import UserAffinityProfile


class UserAffinityProfileBuilder:
    """Compiles unstructured memory entries and explicit attributes into UserAffinityProfile."""

    @staticmethod
    def build_from_attributes(
        user_id: str,
        core_identity: str,
        active_projects: list[str] | None = None,
        tech_stack: list[str] | None = None,
        key_interests: list[str] | None = None,
        negative_filters: list[str] | None = None,
        known_knowledge_signatures: set[str] | None = None,
    ) -> UserAffinityProfile:
        """Create a sanitized and deduplicated UserAffinityProfile."""
        clean_projects = UserAffinityProfileBuilder._deduplicate_strings(
            active_projects or []
        )
        clean_tech = UserAffinityProfileBuilder._deduplicate_strings(
            tech_stack or []
        )
        clean_interests = UserAffinityProfileBuilder._deduplicate_strings(
            key_interests or []
        )
        clean_negatives = UserAffinityProfileBuilder._deduplicate_strings(
            negative_filters or [
                "giveaway",
                "airdrop",
                "retweet to win",
                "crypto pump",
                "discord invite",
                "affiliate link",
                "sponsored post",
            ]
        )
        clean_signatures = frozenset(
            item.strip().lower()
            for item in (known_knowledge_signatures or set())
            if item.strip()
        )

        return UserAffinityProfile(
            user_id=user_id.strip(),
            core_identity=core_identity.strip() or "Senior Software Architect",
            active_projects=clean_projects,
            tech_stack=clean_tech,
            key_interests=clean_interests,
            negative_filters=clean_negatives,
            known_knowledge_signatures=clean_signatures,
        )

    @staticmethod
    def build_from_memory_dict(
        user_id: str,
        memory_payload: Mapping[str, list[str] | str],
    ) -> UserAffinityProfile:
        """Extract profile dimensions from structured memory payload mappings."""
        raw_identity = memory_payload.get("identity") or memory_payload.get("role")
        identity = str(raw_identity) if raw_identity else "Senior Full-Stack AI Engineer"

        projects_val = memory_payload.get("active_projects") or memory_payload.get("projects") or []
        projects = [str(p) for p in projects_val] if isinstance(projects_val, list) else [str(projects_val)]

        tech_val = memory_payload.get("tech_stack") or memory_payload.get("technologies") or []
        tech = [str(t) for t in tech_val] if isinstance(tech_val, list) else [str(tech_val)]

        interests_val = memory_payload.get("interests") or memory_payload.get("topics") or []
        interests = [str(i) for i in interests_val] if isinstance(interests_val, list) else [str(interests_val)]

        neg_val = memory_payload.get("negative_filters") or memory_payload.get("disliked_topics") or []
        negatives = [str(n) for n in neg_val] if isinstance(neg_val, list) else [str(neg_val)]

        known_val = memory_payload.get("known_facts") or memory_payload.get("established_knowledge") or []
        known_set = {str(k).strip().lower() for k in known_val} if isinstance(known_val, list) else {str(known_val).strip().lower()}

        return UserAffinityProfileBuilder.build_from_attributes(
            user_id=user_id,
            core_identity=identity,
            active_projects=projects,
            tech_stack=tech,
            key_interests=interests,
            negative_filters=negatives,
            known_knowledge_signatures=known_set,
        )

    @staticmethod
    def _deduplicate_strings(items: list[str]) -> list[str]:
        """Strip and preserve order deduplication."""
        seen: set[str] = set()
        result: list[str] = []
        for raw in items:
            cleaned = raw.strip()
            lower_val = cleaned.lower()
            if cleaned and lower_val not in seen:
                seen.add(lower_val)
                result.append(cleaned)
        return result
