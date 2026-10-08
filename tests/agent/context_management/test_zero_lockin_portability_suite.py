# [INPUT] zero_lockin_portability package modules
# [OUTPUT] Comprehensive unit test suite for zero-lockin portability and memory hydration
# [POS] Tests for cross-platform ingestion, offline memory hydration, universal archive spec, and health rating

"""Comprehensive test suite for ZeroLockinUniversalContextPortabilitySuite."""

import json
import pytest

from myrm_agent_harness.agent import (
    BilateralSovereigntyArchiveHub,
    CrossPlatformTranscriptNormalizer,
    OfflineMemoryProfileHydrationEngine,
    UniversalArchiveSpecEngine,
    ZeroLockinUniversalContextPortabilitySuite,
)
from myrm_agent_harness.agent.context_management import (
    ARCHIVE_SPEC_VERSION,
    ArchivedSessionNode,
    ArchivedSessionTree,
    ExportPlatformType,
    ExtractedEntityFact,
    HydratedUserProfile,
    UniversalArchivePayload,
    ZeroLockinArchiveManifest,
)


def test_top_level_exports() -> None:
    """Verify all top-level exports and aliases are available."""
    assert ZeroLockinUniversalContextPortabilitySuite is BilateralSovereigntyArchiveHub
    assert ARCHIVE_SPEC_VERSION == "1.0.0"


def test_universal_archive_spec_serialization_and_integrity() -> None:
    """Verify canonical serialization, deserialization, and deterministic SHA-256 checksum."""
    node1 = ArchivedSessionNode(
        node_id="n1",
        parent_id=None,
        children_ids=["n2"],
        role="user",
        content="Hello, what is Python?",
        created_at_unix=1700000000.0,
    )
    node2 = ArchivedSessionNode(
        node_id="n2",
        parent_id="n1",
        children_ids=[],
        role="assistant",
        content="Python is a high-level programming language.",
        created_at_unix=1700000001.0,
    )
    tree = ArchivedSessionTree(
        session_id="sess_1",
        title="Intro to Python",
        root_node_ids=["n1"],
        nodes={"n1": node1, "n2": node2},
        created_at_iso="2026-10-01T00:00:00Z",
        updated_at_iso="2026-10-01T00:01:00Z",
        original_platform="chatgpt",
    )

    fact = ExtractedEntityFact(
        fact_id="f1",
        category="preference",
        subject="sovereign_user",
        predicate="prefers",
        object_value="python",
        confidence=0.9,
        source_session_id="sess_1",
        context_snippet="I prefer Python",
    )
    profile = HydratedUserProfile(
        user_id="sovereign_user",
        preferred_languages=["python"],
        tech_stack_tags=["python"],
        coding_style_rules=["PEP8"],
        high_frequency_topics=["programming"],
        facts=[fact],
        hydration_timestamp=1700000002.0,
    )

    checksum = UniversalArchiveSpecEngine.calculate_checksum([tree], profile)
    manifest = ZeroLockinArchiveManifest(
        version=ARCHIVE_SPEC_VERSION,
        exported_platform="universal_myrm",
        export_timestamp=1700000003.0,
        session_count=1,
        message_count=2,
        entity_fact_count=1,
        checksum_sha256=checksum,
    )
    payload = UniversalArchivePayload(
        manifest=manifest,
        sessions=[tree],
        user_profile=profile,
    )

    # 1. Serialization
    json_str = UniversalArchiveSpecEngine.serialize_payload(payload)
    assert "Intro to Python" in json_str
    assert "sovereign_user" in json_str

    # 2. Deserialization
    restored = UniversalArchiveSpecEngine.deserialize_payload(json_str)
    assert restored.manifest.session_count == 1
    assert len(restored.sessions) == 1
    assert restored.sessions[0].session_id == "sess_1"
    assert restored.sessions[0].nodes["n1"].content == "Hello, what is Python?"
    assert restored.user_profile is not None
    assert restored.user_profile.facts[0].object_value == "python"

    # 3. Integrity verification
    valid, errors = UniversalArchiveSpecEngine.verify_integrity(restored)
    assert valid is True
    assert len(errors) == 0

    # 4. Tampered checksum verification
    tampered_manifest = ZeroLockinArchiveManifest(
        version=ARCHIVE_SPEC_VERSION,
        exported_platform="universal_myrm",
        export_timestamp=1700000003.0,
        session_count=1,
        message_count=2,
        entity_fact_count=1,
        checksum_sha256="bad_checksum_hash",
    )
    tampered_payload = UniversalArchivePayload(
        manifest=tampered_manifest,
        sessions=[tree],
        user_profile=profile,
    )
    is_ok, errs = UniversalArchiveSpecEngine.verify_integrity(tampered_payload)
    assert is_ok is False
    assert any("Checksum mismatch" in e for e in errs)


def test_chatgpt_conversations_export_normalization() -> None:
    """Verify parsing ChatGPT mapping tree structures with branching and empty root nodes."""
    raw_chatgpt_data = [
        {
            "id": "gpt_conv_123",
            "title": "Async Architecture Design",
            "create_time": 1700000000.0,
            "update_time": 1700000060.0,
            "mapping": {
                "root_placeholder": {
                    "id": "root_placeholder",
                    "parent": None,
                    "children": ["turn_user_1"],
                    "message": None,  # System root placeholder
                },
                "turn_user_1": {
                    "id": "turn_user_1",
                    "parent": "root_placeholder",
                    "children": ["turn_assistant_1"],
                    "message": {
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": ["I prefer FastAPI for microservices."]},
                        "create_time": 1700000010.0,
                    },
                },
                "turn_assistant_1": {
                    "id": "turn_assistant_1",
                    "parent": "turn_user_1",
                    "children": [],
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"content_type": "text", "parts": ["FastAPI provides excellent ASGI performance."]},
                        "create_time": 1700000020.0,
                        "metadata": {"model_slug": "gpt-4o"},
                    },
                },
            },
        }
    ]

    json_str = json.dumps(raw_chatgpt_data)
    trees, platform, errors = CrossPlatformTranscriptNormalizer.normalize_archive(json_str)

    assert platform == "chatgpt"
    assert len(errors) == 0
    assert len(trees) == 1

    tree = trees[0]
    assert tree.session_id == "gpt_conv_123"
    assert tree.title == "Async Architecture Design"
    assert len(tree.nodes) == 3
    assert tree.nodes["turn_user_1"].role == "user"
    assert "FastAPI" in tree.nodes["turn_user_1"].content
    assert tree.nodes["turn_assistant_1"].role == "assistant"
    assert tree.nodes["turn_assistant_1"].model_name == "gpt-4o"


def test_claude_web_export_normalization() -> None:
    """Verify parsing Claude Web export structure with linear chat_messages."""
    raw_claude_data = [
        {
            "uuid": "claude_conv_456",
            "name": "Rust Memory Safety Exploration",
            "created_at": "2026-09-01T12:00:00Z",
            "updated_at": "2026-09-01T12:10:00Z",
            "chat_messages": [
                {
                    "uuid": "msg_c1",
                    "sender": "human",
                    "text": "Explain borrow checker rules.",
                    "created_at": "2026-09-01T12:00:10Z",
                },
                {
                    "uuid": "msg_c2",
                    "sender": "assistant",
                    "text": "The borrow checker enforces aliasing XOR mutability.",
                    "created_at": "2026-09-01T12:00:20Z",
                },
            ],
        }
    ]

    json_str = json.dumps(raw_claude_data)
    trees, platform, errors = CrossPlatformTranscriptNormalizer.normalize_archive(json_str)

    assert platform == "claude_web"
    assert len(errors) == 0
    assert len(trees) == 1

    tree = trees[0]
    assert tree.session_id == "claude_conv_456"
    assert tree.title == "Rust Memory Safety Exploration"
    assert len(tree.nodes) == 2
    assert tree.nodes["msg_c1"].role == "user"
    assert tree.nodes["msg_c2"].role == "assistant"
    assert tree.nodes["msg_c2"].parent_id == "msg_c1"


def test_offline_memory_profile_hydration_engine() -> None:
    """Verify extracting entity facts, tech stacks, and user preferences from historical transcripts."""
    node1 = ArchivedSessionNode(
        node_id="m1",
        parent_id=None,
        children_ids=["m2"],
        role="user",
        content="I prefer TypeScript and React. Always use strict typing.",
    )
    node2 = ArchivedSessionNode(
        node_id="m2",
        parent_id="m1",
        children_ids=["m3"],
        role="assistant",
        content="Understood. Strict typing enabled.",
    )
    node3 = ArchivedSessionNode(
        node_id="m3",
        parent_id="m2",
        children_ids=[],
        role="user",
        content="Never use Any in our project. Our project is building an AI compiler.",
    )

    tree = ArchivedSessionTree(
        session_id="dev_session",
        title="Project Setup",
        root_node_ids=["m1"],
        nodes={"m1": node1, "m2": node2, "m3": node3},
        created_at_iso="2026-10-01T00:00:00Z",
        updated_at_iso="2026-10-01T00:05:00Z",
        original_platform="chatgpt",
    )

    profile = OfflineMemoryProfileHydrationEngine.hydrate_profile(
        sessions=[tree],
        user_id="alice_engineer",
    )

    assert profile.user_id == "alice_engineer"
    assert "typescript" in profile.preferred_languages
    assert "react" in profile.tech_stack_tags
    assert len(profile.facts) >= 2

    # Verify fact categories
    predicates = [f.predicate for f in profile.facts]
    assert "prefers" in predicates
    assert "avoids" in predicates

    # Filter high-confidence facts
    high_conf = OfflineMemoryProfileHydrationEngine.filter_high_confidence_facts(profile, threshold=0.85)
    assert len(high_conf) > 0


def test_bilateral_sovereignty_suite_end_to_end_and_health_badge() -> None:
    """Verify end-to-end ingestion, sovereign export, and portability health auditing."""
    raw_export = [
        {
            "id": "full_sess_1",
            "title": "Full Stack Migration",
            "mapping": {
                "u1": {
                    "id": "u1",
                    "parent": None,
                    "children": ["a1"],
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["Please use Docker and Kubernetes for deployment. I prefer Python."]},
                    },
                },
                "a1": {
                    "id": "a1",
                    "parent": "u1",
                    "children": [],
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"parts": ["Configuration ready."]},
                    },
                },
            },
        }
    ]

    json_bytes = json.dumps(raw_export).encode("utf-8")

    # 1. Ingest
    payload, report = BilateralSovereigntyArchiveHub.ingest_external_archive(
        raw_archive=json_bytes,
        user_id="user_bob",
    )
    assert report.success is True
    assert report.imported_sessions == 1
    assert report.imported_messages == 2
    assert report.extracted_facts >= 1
    assert payload.manifest.exported_platform == "chatgpt"

    # 2. Sovereign export
    exported_json, sovereign_payload = BilateralSovereigntyArchiveHub.export_sovereign_archive(
        sessions=payload.sessions,
        profile=payload.user_profile,
    )
    assert sovereign_payload.manifest.exported_platform == "universal_myrm"
    assert "user_bob" in exported_json

    # 3. Assess portability health
    badge = BilateralSovereigntyArchiveHub.assess_portability_health(sovereign_payload)
    assert badge.portability_score >= 85
    assert badge.sovereignty_rating == "FULL_SOVEREIGNTY"
    assert len(badge.warnings) == 0
    assert "Portability Health Score: 100/100" in badge.summary
