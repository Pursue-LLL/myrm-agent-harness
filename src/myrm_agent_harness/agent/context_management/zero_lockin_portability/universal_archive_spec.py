# [INPUT] UniversalArchivePayload, ZeroLockinArchiveManifest, ArchivedSessionTree, ArchivedSessionNode, HydratedUserProfile, ExtractedEntityFact from .portability_types
# [OUTPUT] UniversalArchiveSpecEngine
# [POS] Serialization, deserialization, and SHA-256 integrity verification engine for zero-lockin archives

"""Universal archive specification engine for zero-lockin context portability."""

from __future__ import annotations

import hashlib
import json
import time
from typing import cast

from .portability_types import (
    ArchivedSessionNode,
    ArchivedSessionTree,
    ExportPlatformType,
    ExtractedEntityFact,
    HydratedUserProfile,
    MemoryFactCategory,
    NodeRole,
    UniversalArchivePayload,
    ZeroLockinArchiveManifest,
)

ARCHIVE_SPEC_VERSION = "1.0.0"


class UniversalArchiveSpecEngine:
    """Engine responsible for canonical serialization, deserialization, and integrity validation."""

    @staticmethod
    def calculate_checksum(
        sessions: list[ArchivedSessionTree],
        profile: HydratedUserProfile | None,
    ) -> str:
        """Compute deterministic SHA-256 checksum over conversational tree and profile data."""
        hasher = hashlib.sha256()
        # Sort session IDs for deterministic order
        for tree in sorted(sessions, key=lambda s: s.session_id):
            hasher.update(tree.session_id.encode("utf-8"))
            hasher.update(str(len(tree.nodes)).encode("utf-8"))
            for node_id in sorted(tree.nodes.keys()):
                node = tree.nodes[node_id]
                hasher.update(node.node_id.encode("utf-8"))
                hasher.update(node.role.encode("utf-8"))
                hasher.update(node.content.encode("utf-8"))

        if profile is not None:
            hasher.update(profile.user_id.encode("utf-8"))
            for fact in sorted(profile.facts, key=lambda f: f.fact_id):
                hasher.update(fact.fact_id.encode("utf-8"))
                hasher.update(fact.subject.encode("utf-8"))
                hasher.update(fact.predicate.encode("utf-8"))
                hasher.update(fact.object_value.encode("utf-8"))

        return hasher.hexdigest()

    @classmethod
    def serialize_payload(cls, payload: UniversalArchivePayload) -> str:
        """Serialize UniversalArchivePayload to a standard JSON string."""
        serialized_sessions: list[dict[str, object]] = []
        for tree in payload.sessions:
            nodes_dict: dict[str, dict[str, object]] = {}
            for node_id, node in tree.nodes.items():
                nodes_dict[node_id] = {
                    "node_id": node.node_id,
                    "parent_id": node.parent_id,
                    "children_ids": node.children_ids,
                    "role": node.role,
                    "content": node.content,
                    "thoughts": node.thoughts,
                    "model_name": node.model_name,
                    "created_at_unix": node.created_at_unix,
                    "metadata": node.metadata,
                }
            serialized_sessions.append({
                "session_id": tree.session_id,
                "title": tree.title,
                "root_node_ids": tree.root_node_ids,
                "nodes": nodes_dict,
                "created_at_iso": tree.created_at_iso,
                "updated_at_iso": tree.updated_at_iso,
                "original_platform": tree.original_platform,
                "tags": tree.tags,
            })

        serialized_profile: dict[str, object] | None = None
        if payload.user_profile is not None:
            serialized_facts: list[dict[str, object]] = [
                {
                    "fact_id": f.fact_id,
                    "category": f.category,
                    "subject": f.subject,
                    "predicate": f.predicate,
                    "object_value": f.object_value,
                    "confidence": f.confidence,
                    "source_session_id": f.source_session_id,
                    "context_snippet": f.context_snippet,
                }
                for f in payload.user_profile.facts
            ]
            serialized_profile = {
                "user_id": payload.user_profile.user_id,
                "preferred_languages": payload.user_profile.preferred_languages,
                "tech_stack_tags": payload.user_profile.tech_stack_tags,
                "coding_style_rules": payload.user_profile.coding_style_rules,
                "high_frequency_topics": payload.user_profile.high_frequency_topics,
                "facts": serialized_facts,
                "hydration_timestamp": payload.user_profile.hydration_timestamp,
            }

        archive_dict: dict[str, object] = {
            "manifest": {
                "version": payload.manifest.version,
                "exported_platform": payload.manifest.exported_platform,
                "export_timestamp": payload.manifest.export_timestamp,
                "session_count": payload.manifest.session_count,
                "message_count": payload.manifest.message_count,
                "entity_fact_count": payload.manifest.entity_fact_count,
                "checksum_sha256": payload.manifest.checksum_sha256,
                "description": payload.manifest.description,
            },
            "sessions": serialized_sessions,
            "user_profile": serialized_profile,
        }
        return json.dumps(archive_dict, indent=2, ensure_ascii=False)

    @classmethod
    def deserialize_payload(cls, json_str: str) -> UniversalArchivePayload:
        """Parse JSON string and reconstruct typed UniversalArchivePayload."""
        raw_data = cast(dict[str, object], json.loads(json_str))
        manifest_raw = cast(dict[str, object], raw_data.get("manifest", {}))

        manifest = ZeroLockinArchiveManifest(
            version=str(manifest_raw.get("version", ARCHIVE_SPEC_VERSION)),
            exported_platform=cast(
                ExportPlatformType,
                manifest_raw.get("exported_platform", "unknown"),
            ),
            export_timestamp=float(
                cast(int | float, manifest_raw.get("export_timestamp", time.time()))
            ),
            session_count=int(cast(int, manifest_raw.get("session_count", 0))),
            message_count=int(cast(int, manifest_raw.get("message_count", 0))),
            entity_fact_count=int(cast(int, manifest_raw.get("entity_fact_count", 0))),
            checksum_sha256=str(manifest_raw.get("checksum_sha256", "")),
            description=str(manifest_raw.get("description", "")),
        )

        sessions: list[ArchivedSessionTree] = []
        raw_sessions = cast(list[dict[str, object]], raw_data.get("sessions", []))
        for raw_sess in raw_sessions:
            raw_nodes = cast(dict[str, dict[str, object]], raw_sess.get("nodes", {}))
            nodes: dict[str, ArchivedSessionNode] = {}
            for node_id, raw_node in raw_nodes.items():
                metadata_raw = cast(dict[str, object], raw_node.get("metadata", {}))
                metadata = {str(k): str(v) for k, v in metadata_raw.items()}
                raw_children = cast(list[object], raw_node.get("children_ids", []))
                children_ids = [str(c) for c in raw_children]

                node = ArchivedSessionNode(
                    node_id=str(raw_node.get("node_id", node_id)),
                    parent_id=(
                        str(raw_node["parent_id"])
                        if raw_node.get("parent_id") is not None
                        else None
                    ),
                    children_ids=children_ids,
                    role=cast(NodeRole, raw_node.get("role", "user")),
                    content=str(raw_node.get("content", "")),
                    thoughts=(
                        str(raw_node["thoughts"])
                        if raw_node.get("thoughts") is not None
                        else None
                    ),
                    model_name=(
                        str(raw_node["model_name"])
                        if raw_node.get("model_name") is not None
                        else None
                    ),
                    created_at_unix=float(
                        cast(int | float, raw_node.get("created_at_unix", 0.0))
                    ),
                    metadata=metadata,
                )
                nodes[node_id] = node

            root_nodes_raw = cast(list[object], raw_sess.get("root_node_ids", []))
            tags_raw = cast(list[object], raw_sess.get("tags", []))
            sess_tree = ArchivedSessionTree(
                session_id=str(raw_sess.get("session_id", "")),
                title=str(raw_sess.get("title", "Untitled")),
                root_node_ids=[str(r) for r in root_nodes_raw],
                nodes=nodes,
                created_at_iso=str(raw_sess.get("created_at_iso", "")),
                updated_at_iso=str(raw_sess.get("updated_at_iso", "")),
                original_platform=cast(
                    ExportPlatformType,
                    raw_sess.get("original_platform", "unknown"),
                ),
                tags=[str(t) for t in tags_raw],
            )
            sessions.append(sess_tree)

        profile: HydratedUserProfile | None = None
        raw_profile = cast(dict[str, object] | None, raw_data.get("user_profile"))
        if raw_profile is not None:
            raw_facts = cast(list[dict[str, object]], raw_profile.get("facts", []))
            facts: list[ExtractedEntityFact] = []
            for rf in raw_facts:
                fact = ExtractedEntityFact(
                    fact_id=str(rf.get("fact_id", "")),
                    category=cast(MemoryFactCategory, rf.get("category", "preference")),
                    subject=str(rf.get("subject", "")),
                    predicate=str(rf.get("predicate", "")),
                    object_value=str(rf.get("object_value", "")),
                    confidence=float(cast(int | float, rf.get("confidence", 1.0))),
                    source_session_id=str(rf.get("source_session_id", "")),
                    context_snippet=str(rf.get("context_snippet", "")),
                )
                facts.append(fact)

            pref_langs = [
                str(x)
                for x in cast(list[object], raw_profile.get("preferred_languages", []))
            ]
            tech_tags = [
                str(x) for x in cast(list[object], raw_profile.get("tech_stack_tags", []))
            ]
            coding_rules = [
                str(x)
                for x in cast(list[object], raw_profile.get("coding_style_rules", []))
            ]
            freq_topics = [
                str(x)
                for x in cast(list[object], raw_profile.get("high_frequency_topics", []))
            ]

            profile = HydratedUserProfile(
                user_id=str(raw_profile.get("user_id", "default_user")),
                preferred_languages=pref_langs,
                tech_stack_tags=tech_tags,
                coding_style_rules=coding_rules,
                high_frequency_topics=freq_topics,
                facts=facts,
                hydration_timestamp=float(
                    cast(int | float, raw_profile.get("hydration_timestamp", 0.0))
                ),
            )

        return UniversalArchivePayload(
            manifest=manifest,
            sessions=sessions,
            user_profile=profile,
        )

    @classmethod
    def verify_integrity(
        cls, payload: UniversalArchivePayload
    ) -> tuple[bool, list[str]]:
        """Verify checksum, message counts, and node reference integrity."""
        errors: list[str] = []
        expected_checksum = cls.calculate_checksum(
            payload.sessions, payload.user_profile
        )

        if (
            payload.manifest.checksum_sha256
            and payload.manifest.checksum_sha256 != expected_checksum
        ):
            errors.append(
                f"Checksum mismatch: manifest '{payload.manifest.checksum_sha256[:12]}...' "
                f"!= computed '{expected_checksum[:12]}...'"
            )

        actual_sessions = len(payload.sessions)
        if (
            payload.manifest.session_count > 0
            and actual_sessions != payload.manifest.session_count
        ):
            errors.append(
                f"Session count mismatch: manifest {payload.manifest.session_count} "
                f"!= actual {actual_sessions}"
            )

        actual_messages = sum(len(s.nodes) for s in payload.sessions)
        if (
            payload.manifest.message_count > 0
            and actual_messages != payload.manifest.message_count
        ):
            errors.append(
                f"Message count mismatch: manifest {payload.manifest.message_count} "
                f"!= actual {actual_messages}"
            )

        # Verify parent-child references inside session trees
        for tree in payload.sessions:
            for node_id, node in tree.nodes.items():
                if node.parent_id and node.parent_id not in tree.nodes:
                    errors.append(
                        f"Dangling parent reference in session '{tree.session_id}': "
                        f"node '{node_id}' references unknown parent '{node.parent_id}'"
                    )
                for child_id in node.children_ids:
                    if child_id not in tree.nodes:
                        errors.append(
                            f"Dangling child reference in session '{tree.session_id}': "
                            f"node '{node_id}' references unknown child '{child_id}'"
                        )

        return (len(errors) == 0, errors)
