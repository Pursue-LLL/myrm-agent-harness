"""Desktop control health probe for the doctor.

[INPUT]
- toolkits.computer_use.session::create_computer_session (POS: Computer session factory; its `check_permissions(probe_capture=True)` is the same backend probe as `GET /webui/desktop/permissions`)
- diagnostics.protocols::HealthReport (POS: Standard health check report)

[OUTPUT]
- check_desktop_permissions_health: DesktopControl probe, grants plus capture (`probe_capture=True`); PASS only when `PermissionStatus.capture_ready`.

[POS]
Harness-level doctor probe registered through probes.py; kept apart so the probe module stays within its line budget.
"""

import logging
import os

from myrm_agent_harness.observability.diagnostics.protocols import HealthReport

logger = logging.getLogger(__name__)


async def check_desktop_permissions_health() -> HealthReport:
    """Probe OS permissions required for semantic desktop control (computer_use).

    Reuses the same backend probe as ``GET /webui/desktop/permissions`` on the
    server. Skipped on cloud sandbox deploy mode where local OS grants do not apply.
    """
    deploy_mode = os.getenv("DEPLOY_MODE", "local").lower()
    if deploy_mode == "sandbox":
        visual_desktop = os.getenv("VISUAL_DESKTOP", "0") == "1"
        if visual_desktop:
            return HealthReport(
                component_name="DesktopControl",
                status="pass",
                code="OK_DESKTOP_SANDBOX_VNC",
                message="Cloud sandbox visual desktop is enabled (VNC entitlement).",
                detail="Local Accessibility/Screen Recording checks apply to local and Tauri modes only.",
            )
        return HealthReport(
            component_name="DesktopControl",
            status="warn",
            code="WARN_DESKTOP_SANDBOX_UNAVAILABLE",
            message="Desktop control is unavailable in this cloud sandbox.",
            detail="Enable the visual desktop (VNC) entitlement for computer_use in cloud hosting.",
            fix_suggestion="Upgrade your plan or enable VNC in agent settings before using desktop control.",
        )

    session = None
    try:
        from myrm_agent_harness.toolkits.computer_use.session import create_computer_session

        session = create_computer_session()
        status = await session.check_permissions(probe_capture=True)
    except Exception as exc:
        logger.warning("Desktop permissions probe failed: %s", exc)
        return HealthReport(
            component_name="DesktopControl",
            status="fail",
            code="ERR_DESKTOP_PERMISSIONS_PROBE",
            message="Desktop permission check failed.",
            detail=str(exc),
            fix_suggestion="Ensure computer_use dependencies are installed and retry from Settings.",
        )
    finally:
        if session is not None:
            await session.close()

    missing: list[str] = []
    if not status.accessibility:
        missing.append("Accessibility")
    if not status.screen_recording:
        missing.append("Screen Recording")

    platform_label = status.platform or "local"
    capturable = status.screen_recording_capturable

    # PASS iff PermissionStatus.capture_ready (grants OK ∧ capturable is True).
    if status.capture_ready:
        return HealthReport(
            component_name="DesktopControl",
            status="pass",
            code="OK_DESKTOP_PERMISSIONS",
            message="Desktop permissions are granted and capture is ready.",
            detail=(f"Platform: {platform_label}. Accessibility, Screen Recording, and usable screen capture are OK."),
            meta_data={
                "accessibility": status.accessibility,
                "screen_recording": status.screen_recording,
                "screen_recording_capturable": capturable,
                "capture_ready": True,
                "platform": platform_label,
            },
        )

    if not missing:
        return HealthReport(
            component_name="DesktopControl",
            status="warn",
            code="WARN_DESKTOP_CAPTURE_NOT_READY",
            message="Desktop permissions look granted but screen capture is not usable.",
            detail=(
                f"Platform: {platform_label}. Screen capture did not return a usable "
                "frame (empty, pure-black/white, or capture tools unavailable). "
                "Re-grant Screen Recording and unlock the display, then recheck."
            ),
            fix_suggestion=("Re-enable Screen Recording for this app, unlock the display, then recheck from Settings."),
            meta_data={
                "accessibility": status.accessibility,
                "screen_recording": status.screen_recording,
                "screen_recording_capturable": capturable,
                "capture_ready": False,
                "platform": platform_label,
                "settings_deeplinks": status.settings_deeplinks,
            },
        )

    missing_text = ", ".join(missing)
    return HealthReport(
        component_name="DesktopControl",
        status="warn",
        code="WARN_DESKTOP_PERMISSIONS_MISSING",
        message=f"Missing desktop permissions: {missing_text}.",
        detail=f"Platform: {platform_label}. Grant {missing_text} before using desktop control.",
        fix_suggestion="Grant the missing permissions in system settings, then recheck.",
        meta_data={
            "missing": missing_text,
            "accessibility": status.accessibility,
            "screen_recording": status.screen_recording,
            "screen_recording_capturable": capturable,
            "capture_ready": False,
            "platform": platform_label,
            "settings_deeplinks": status.settings_deeplinks,
        },
    )
