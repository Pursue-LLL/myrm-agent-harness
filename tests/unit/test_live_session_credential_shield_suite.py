"""
[POS] tests/unit/test_live_session_credential_shield_suite.py
[INPUT] pytest, myrm_agent_harness.core.security.live_session_credential_shield
[OUTPUT] Unit tests for LiveSessionCredentialShieldSuite

Validates out-of-band blind input routing, screen bounding box mask registration,
DOM password attribute redaction, and atomic handover scrub against prompt injection.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.live_session_credential_shield import (
    AirlockChannelStatus,
    BoundingBox,
    LiveSessionCredentialShieldSuite,
    SensitiveTargetType,
)


def test_airlock_channel_lifecycle_and_blind_input() -> None:
    """Validate out-of-band channel management and leak-free blind credential routing."""
    suite = LiveSessionCredentialShieldSuite()
    session_id = "sess-takeover-001"

    # 1. Open airlock channel
    status = suite.open_airlock(session_id)
    assert status == AirlockChannelStatus.OPEN
    assert suite.get_airlock_status(session_id) == AirlockChannelStatus.OPEN

    # 2. Route password input
    event, dispatch_id = suite.route_blind_input(
        session_id=session_id,
        target_selector="form#login input[type='password']",
        raw_secret="P@ssw0rd2026!Secret",
    )
    assert event.is_blind_routed is True
    assert event.target_type == SensitiveTargetType.PASSWORD_INPUT
    assert event.keystroke_count == len("P@ssw0rd2026!Secret")
    assert dispatch_id.startswith("oob-disp-")

    # 3. Route 2FA OTP input
    event_otp, _ = suite.route_blind_input(
        session_id=session_id,
        target_selector="input#verification-code-otp",
        raw_secret="789012",
    )
    assert event_otp.target_type == SensitiveTargetType.OTP_INPUT
    assert event_otp.keystroke_count == 6

    # 4. Check historical events
    events = suite.list_session_blind_events(session_id)
    assert len(events) == 2

    # 5. Close airlock
    closed_status = suite.close_airlock(session_id)
    assert closed_status == AirlockChannelStatus.CLOSED


def test_screen_mask_region_registration() -> None:
    """Validate screen pixel masking bounding box registration."""
    suite = LiveSessionCredentialShieldSuite()
    session_id = "sess-vnc-002"

    region = suite.register_mask_region(
        session_id=session_id,
        box=BoundingBox(x=120, y=340, width=280, height=45),
        target_selector="input#card-cvv",
        mask_color="#111111",
    )
    assert region.region_id.startswith("mask-reg-")
    assert region.box.width == 280
    assert region.box.height == 45

    regions = suite.list_mask_regions(session_id)
    assert len(regions) == 1
    assert regions[0].target_selector == "input#card-cvv"


def test_dom_redaction_and_prompt_injection_scrubbing() -> None:
    """Validate scrubbing of password attributes and technological tokens from DOM trees."""
    suite = LiveSessionCredentialShieldSuite()

    sample_dom = """
    <div class="login-box">
      <input type="text" name="username" value="developer_alice" />
      <input type="password" id="user-pass" value="SuperSecretCleartextPassword" />
      <input name="cvv" value="999" />
      <p>System Token for debugging: sk-proj-12345678901234567890abcdef</p>
    </div>
    """

    sanitized_html, redacted_count = suite.redact_dom_tree(sample_dom)

    # Values must be obscured
    assert "SuperSecretCleartextPassword" not in sanitized_html
    assert "999" not in sanitized_html
    assert "sk-proj-12345678901234567890abcdef" not in sanitized_html
    assert "<REDACTED_CREDENTIAL>" in sanitized_html
    assert redacted_count >= 3

    # Safe attributes remain unchanged
    assert "developer_alice" in sanitized_html


def test_handover_scrub_atomic_workflow() -> None:
    """Validate atomic screen-DOM scrub report generation when returning control to Agent."""
    suite = LiveSessionCredentialShieldSuite()
    session_id = "sess-handover-003"

    # Register mask region
    suite.register_mask_region(
        session_id=session_id,
        box=BoundingBox(x=10, y=20, width=100, height=30),
        target_selector="#secret-token",
    )

    # Route blind input
    suite.route_blind_input(
        session_id=session_id,
        target_selector="input[type='password']",
        raw_secret="mypassword",
    )

    raw_dom = "<input type='password' value='hunter2' />"
    sanitized_dom, report = suite.execute_handover_scrub(session_id, raw_dom)

    assert "hunter2" not in sanitized_dom
    assert report.observation_scrubbed is True
    assert report.masked_regions_count == 1
    assert report.redacted_dom_nodes_count == 1

    # Metrics
    metrics = suite.metrics
    assert metrics.blind_inputs_routed_total == 1
    assert metrics.screen_masks_applied_total == 1
    assert metrics.handover_scrubs_completed_total == 1
    assert metrics.prompt_injections_mitigated_total >= 1
