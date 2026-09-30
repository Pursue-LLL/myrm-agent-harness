"""Unit tests for noise-stripped semantic fingerprinting and anomaly detection."""

from myrm_agent_harness.runtime.loop.fingerprint import (
    extract_semantic_fingerprint,
    has_alert_anomaly,
)


def test_semantic_fingerprint_strips_clock_and_temporal_noise() -> None:
    # Two responses with identical status but differing clock and duration noise
    resp1 = "Build in progress. Checked at 14:02:11 on 2026-09-30. Duration: 1.2s. [/loop wakeup #1]"
    resp2 = "Build in progress. Checked at 14:05:49 on 2026-09-30. Duration: 3.8s. [/loop wakeup #2]"

    fp1 = extract_semantic_fingerprint(resp1)
    fp2 = extract_semantic_fingerprint(resp2)

    assert fp1, "Fingerprint should not be empty"
    assert fp1 == fp2, "Fingerprints must be identical despite clock and duration differences"


def test_semantic_fingerprint_detects_substantive_change() -> None:
    resp1 = "Tests running: 12/50 passed."
    resp2 = "Tests running: 48/50 passed."

    fp1 = extract_semantic_fingerprint(resp1)
    fp2 = extract_semantic_fingerprint(resp2)

    assert fp1 != fp2, "Substantive state difference must yield different fingerprints"


def test_has_alert_anomaly_detection() -> None:
    assert has_alert_anomaly("Everything failed with fatal error!")
    assert has_alert_anomaly("Process exited with exit code 1.")
    assert has_alert_anomaly("Encountered Out Of Memory error.")
    assert has_alert_anomaly("Traceback (most recent call last):\n  File 'test.py', line 12")
    assert not has_alert_anomaly("Normal operational output without any issues.")
