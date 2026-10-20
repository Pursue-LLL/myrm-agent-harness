"""
Tests for In-App Live Diagnostics Bundle models and packager.
"""

from myrm_agent_harness.observability.diagnostics_bundle.models import (
    ClientContext,
    DiagnosticLogEvent,
    EncryptedDiagnosticBundle,
    SandboxVitals,
)
from myrm_agent_harness.observability.diagnostics_bundle.packager import (
    DiagnosticBundlePackager,
)


def test_pii_scrubbing_rules() -> None:
    packager = DiagnosticBundlePackager()

    raw_text = (
        "Encountered error with Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret "
        "and sk-proj-1234567890abcdef12345678. Contact dev user@example.com or +1 800-555-0199."
    )
    scrubbed, count = packager.scrub_text(raw_text)

    assert "Bearer ***REDACTED***" in scrubbed
    assert "sk-***REDACTED***" in scrubbed
    assert "***@***.***" in scrubbed
    assert "***-***-****" in scrubbed
    assert count >= 4


def test_bundle_packaging_and_hmac_integrity() -> None:
    packager = DiagnosticBundlePackager()

    vitals = SandboxVitals(
        cpu_pct=88.5,
        mem_pct=92.1,
        disk_free_bytes=1024 * 1024 * 200,
        network_state="degraded",
        uptime_secs=3600.0,
        is_volume_healthy=True,
    )

    logs = [
        DiagnosticLogEvent(
            timestamp="2026-10-12T12:00:00Z",
            level="ERROR",
            subsystem="sandbox_kernel",
            message="Connection timeout connecting to upstream with token=sk-abc12345678901234567890",
            metadata={"caller": "operator@test.org"},
        )
    ]

    client_context = ClientContext(
        client_version="1.4.0",
        platform="darwin",
        browser_or_os="Chrome 130 / macOS 15.0",
        active_route="/workspace/agent-42",
        session_id="session-9988",
    )

    bundle = packager.package(
        session_id="session-9988",
        sandbox_id="sandbox-box-12",
        vitals=vitals,
        raw_logs=logs,
        client_context=client_context,
    )

    # Assert integrity matches
    assert packager.verify_integrity(bundle) is True
    assert bundle.scrubbed_pii_count >= 2
    assert "***REDACTED***" in bundle.logs[0].message
    assert "***@***.***" in bundle.logs[0].metadata["caller"]

    # Tampering test
    tampered_bundle = EncryptedDiagnosticBundle(
        bundle_id=bundle.bundle_id,
        session_id=bundle.session_id,
        sandbox_id="sandbox-box-TAMPERED",
        vitals=bundle.vitals,
        logs=bundle.logs,
        client_context=bundle.client_context,
        scrubbed_pii_count=bundle.scrubbed_pii_count,
        checksum=bundle.checksum,
        created_at=bundle.created_at,
    )
    assert packager.verify_integrity(tampered_bundle) is False


def test_log_truncation_limits() -> None:
    packager = DiagnosticBundlePackager(max_logs=5)

    vitals = SandboxVitals(
        cpu_pct=10.0,
        mem_pct=20.0,
        disk_free_bytes=1000000,
        network_state="healthy",
        uptime_secs=50.0,
    )

    logs = [
        DiagnosticLogEvent(
            timestamp=f"2026-10-12T12:00:{i:02d}Z",
            level="INFO",
            subsystem="agent",
            message=f"Step log item {i}",
        )
        for i in range(15)
    ]

    client_context = ClientContext(
        client_version="1.0.0",
        platform="web",
        browser_or_os="Safari",
        active_route="/chat",
        session_id="sess-1",
    )

    bundle = packager.package(
        session_id="sess-1",
        sandbox_id="box-1",
        vitals=vitals,
        raw_logs=logs,
        client_context=client_context,
    )

    # Must only keep last 5 logs
    assert len(bundle.logs) == 5
    assert bundle.logs[-1].message == "Step log item 14"
    assert bundle.logs[0].message == "Step log item 10"
