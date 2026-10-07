"""Unit tests for SessionLifecycleLogArchiverAndOfflineBundleExportEngine (Item 100).

Validates structured execution archiving, credential sanitization,
self-contained offline HTML rendering, JSON bundle serialization,
checksum tamper detection, and lossless import recovery.
"""

import json

from myrm_agent_harness.runtime.context.session_lifecycle_log_archiver import (
    SessionLifecycleLogArchiverAndOfflineBundleExportEngine,
)
from myrm_agent_harness.runtime.context.session_lifecycle_log_archiver_types import (
    ArtifactSnapshotEntry,
    SanitizationPolicy,
    SessionExecutionTurn,
    TokenCostBillingSnapshot,
    ToolExecutionLogEntry,
    ToolExecutionStatus,
)


def _build_sample_session_turns() -> list[SessionExecutionTurn]:
    """Helper to construct realistic multi-turn session records."""
    t1_tools = [
        ToolExecutionLogEntry(
            call_id="call_001",
            tool_name="bash_execute",
            arguments={"command": "grep -rn 'DATABASE_URL' /Users/johndoe/projects/my-app"},
            result_payload="DATABASE_URL=postgres://user:pass@10.0.1.42:5432/db",
            duration_ms=42.5,
            status=ToolExecutionStatus.SUCCESS,
            timestamp="2026-10-07T10:00:01Z",
        ),
        ToolExecutionLogEntry(
            call_id="call_002",
            tool_name="read_file",
            arguments={"path": "/Users/johndoe/projects/my-app/config.json"},
            result_payload='{"openai_key": "sk-proj99887766554433221100aa", "owner": "admin@myrm.ai"}',
            duration_ms=12.0,
            status=ToolExecutionStatus.SUCCESS,
            timestamp="2026-10-07T10:00:03Z",
        ),
    ]

    turn_1 = SessionExecutionTurn(
        turn_id=1,
        user_input="Please locate the database credentials and OpenAI key in /Users/johndoe/projects/my-app",
        assistant_response="Located configuration. Contact me at support@myrm.ai if needed.",
        tool_calls=t1_tools,
        token_billing=TokenCostBillingSnapshot(
            prompt_tokens=1500,
            completion_tokens=200,
            cache_hit_tokens=1200,
            estimated_cost_usd=0.0035,
        ),
        errors=[],
        timestamp="2026-10-07T10:00:05Z",
    )

    t2_tools = [
        ToolExecutionLogEntry(
            call_id="call_003",
            tool_name="deploy_service",
            arguments={"target": "192.168.1.150"},
            result_payload="Deployment rejected: unauthorized host",
            duration_ms=150.2,
            status=ToolExecutionStatus.FAILED,
            timestamp="2026-10-07T10:01:00Z",
            error_message="Unauthorized host 192.168.1.150 using Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy",
        )
    ]

    turn_2 = SessionExecutionTurn(
        turn_id=2,
        user_input="Retry deployment with Anthropic sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234 key",
        assistant_response="Deployment attempt completed with failure report.",
        tool_calls=t2_tools,
        token_billing=TokenCostBillingSnapshot(
            prompt_tokens=1800,
            completion_tokens=150,
            cache_hit_tokens=1600,
            estimated_cost_usd=0.0028,
        ),
        errors=["Deployment rejected"],
        timestamp="2026-10-07T10:01:05Z",
    )

    return [turn_1, turn_2]


def test_structured_log_archiving_and_token_billing_aggregation() -> None:
    """Validate full lifecycle turn archiving and precise billing rollup."""
    engine = SessionLifecycleLogArchiverAndOfflineBundleExportEngine()
    turns = _build_sample_session_turns()
    artifacts = [
        ArtifactSnapshotEntry(
            artifact_id="art_001",
            name="migration_script.sql",
            mime_type="text/x-sql",
            content_text="ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE;",
            version_hash="a1b2c3d4",
            created_at="2026-10-07T10:00:10Z",
        )
    ]

    bundle = engine.archive_session(
        session_id="sess_prod_999",
        workspace_name="core_backend",
        created_at="2026-10-07T10:00:00Z",
        turns=turns,
        artifacts=artifacts,
        policy=None,
    )

    assert bundle.session_id == "sess_prod_999"
    assert len(bundle.turns) == 2
    assert len(bundle.artifacts) == 1
    assert bundle.is_sanitized is False

    # Check billing aggregation
    assert bundle.total_billing.prompt_tokens == 1500 + 1800
    assert bundle.total_billing.completion_tokens == 200 + 150
    assert bundle.total_billing.cache_hit_tokens == 1200 + 1600
    assert bundle.total_billing.total_tokens == 3300 + 350
    assert round(bundle.total_billing.estimated_cost_usd, 4) == round(0.0035 + 0.0028, 4)
    assert len(bundle.checksum_sha256) == 64


def test_credential_and_pii_sanitization() -> None:
    """Validate robust sanitization of keys, private IPs, home paths, and emails."""
    engine = SessionLifecycleLogArchiverAndOfflineBundleExportEngine()
    turns = _build_sample_session_turns()
    artifacts = [
        ArtifactSnapshotEntry(
            artifact_id="art_env",
            name="env_backup.txt",
            mime_type="text/plain",
            content_text="API_KEY=sk-proj99887766554433221100aa\nHOST=10.0.1.42\nPATH=/Users/johndoe/secrets",
            version_hash="v1",
            created_at="2026-10-07T10:00:10Z",
        )
    ]

    policy = SanitizationPolicy(
        mask_api_keys=True,
        mask_private_ips=True,
        mask_user_home_paths=True,
        mask_emails=True,
    )

    bundle = engine.archive_session(
        session_id="sess_sanitized_001",
        workspace_name="security_audit",
        created_at="2026-10-07T10:00:00Z",
        turns=turns,
        artifacts=artifacts,
        policy=policy,
    )

    assert bundle.is_sanitized is True

    exported_json = engine.export_bundle_json(bundle)

    # Assert raw sensitive tokens are completely scrubbed
    assert "sk-proj99887766554433221100aa" not in exported_json
    assert "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234" not in exported_json
    assert "10.0.1.42" not in exported_json
    assert "192.168.1.150" not in exported_json
    assert "/Users/johndoe" not in exported_json
    assert "admin@myrm.ai" not in exported_json
    assert "support@myrm.ai" not in exported_json

    # Assert masked placeholders are present
    assert "[REDACTED_API_KEY]" in exported_json
    assert "[PRIVATE_IP]" in exported_json
    assert "<HOMEDIR>" in exported_json
    assert "***@***.***" in exported_json


def test_self_contained_offline_html_export() -> None:
    """Validate generation of self-contained offline HTML viewer with zero CDN reliance."""
    engine = SessionLifecycleLogArchiverAndOfflineBundleExportEngine()
    turns = _build_sample_session_turns()
    artifacts = [
        ArtifactSnapshotEntry(
            artifact_id="art_001",
            name="index.ts",
            mime_type="application/typescript",
            content_text="export const version = '1.0.0';",
            version_hash="h1",
            created_at="2026-10-07T10:00:10Z",
        )
    ]

    bundle = engine.archive_session(
        session_id="sess_html_preview",
        workspace_name="frontend_app",
        created_at="2026-10-07T10:00:00Z",
        turns=turns,
        artifacts=artifacts,
    )

    html_content = engine.export_self_contained_html(bundle)

    # Assert self-contained HTML structure
    assert "<!DOCTYPE html>" in html_content
    assert "<html lang=\"en\">" in html_content
    assert "<style>" in html_content
    assert "Myrm Session Lifecycle Log: sess_html_preview" in html_content
    assert "Total Tokens:" in html_content
    assert "Cache Hit Tokens:" in html_content
    assert "bash_execute" in html_content
    assert "deploy_service" in html_content
    assert "index.ts" in html_content

    # Strict offline guarantee: no remote CSS/JS CDNs
    assert "https://" not in html_content
    assert "http://" not in html_content
    assert "<link rel=\"stylesheet\"" not in html_content


def test_offline_json_bundle_serialization_and_checksum_tamper_detection() -> None:
    """Validate JSON export and SHA-256 tamper watchdog rejection."""
    engine = SessionLifecycleLogArchiverAndOfflineBundleExportEngine()
    turns = _build_sample_session_turns()
    artifacts = [
        ArtifactSnapshotEntry(
            artifact_id="art_001",
            name="report.md",
            mime_type="text/markdown",
            content_text="# Title",
            version_hash="h0",
            created_at="2026-10-07T10:00:10Z",
        )
    ]

    bundle = engine.archive_session(
        session_id="sess_tamper_check",
        workspace_name="test_ws",
        created_at="2026-10-07T10:00:00Z",
        turns=turns,
        artifacts=artifacts,
    )

    bundle_json = engine.export_bundle_json(bundle)
    parsed = json.loads(bundle_json)

    # Tamper with assistant response
    parsed["turns"][0]["assistant_response"] = "TAMPERED_INTRUSION_CONTENT"
    tampered_json = json.dumps(parsed)

    restored_bundle, replay_result = engine.import_and_verify(tampered_json)

    assert restored_bundle is None
    assert replay_result.success is False
    assert replay_result.verified_checksum is False
    assert "Integrity check failed: checksum mismatch" in replay_result.message


def test_one_click_import_and_lossless_replay_recovery() -> None:
    """Validate 1-click lossless import and state reconstruction from authentic bundle."""
    engine = SessionLifecycleLogArchiverAndOfflineBundleExportEngine()
    turns = _build_sample_session_turns()
    artifacts = [
        ArtifactSnapshotEntry(
            artifact_id="art_sql",
            name="schema.sql",
            mime_type="text/x-sql",
            content_text="CREATE TABLE test_table (id INT);",
            version_hash="v_sql_1",
            created_at="2026-10-07T10:00:10Z",
        )
    ]

    original_bundle = engine.archive_session(
        session_id="sess_replay_test",
        workspace_name="production_archive",
        created_at="2026-10-07T10:00:00Z",
        turns=turns,
        artifacts=artifacts,
    )

    json_data = engine.export_bundle_json(original_bundle)

    restored_bundle, replay_result = engine.import_and_verify(json_data)

    assert replay_result.success is True
    assert replay_result.verified_checksum is True
    assert replay_result.turn_count == 2
    assert replay_result.artifact_count == 1
    assert replay_result.total_tokens == original_bundle.total_billing.total_tokens
    assert "100% integrity" in replay_result.message

    assert restored_bundle is not None
    assert restored_bundle.session_id == original_bundle.session_id
    assert restored_bundle.checksum_sha256 == original_bundle.checksum_sha256
    assert restored_bundle.turns[0].user_input == original_bundle.turns[0].user_input
    assert restored_bundle.turns[0].tool_calls[0].tool_name == "bash_execute"
    assert restored_bundle.artifacts[0].name == "schema.sql"
