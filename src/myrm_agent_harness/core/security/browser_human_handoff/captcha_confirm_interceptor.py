"""
[POS] src/myrm_agent_harness/core/security/browser_human_handoff/captcha_confirm_interceptor.py
[INPUT] re, time, uuid, typing
[OUTPUT] CaptchaConfirmInterceptor

Default Captcha & Confirm Screen Interception Gate.
Enforces mandatory human fallback as a default system behavior whenever anti-bot challenges
or critical confirm dialogs appear in the browser DOM.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from .types import HandoffInterceptionResult, HandoffTriggerType

logger = logging.getLogger(__name__)


class CaptchaConfirmInterceptor:
    """Interception gate suspending automation upon encountering Captchas or irreversible confirmation dialogs."""

    CAPTCHA_SIGNATURES: tuple[tuple[re.Pattern[str], str], ...] = (
        (
            re.compile(r"""(?:cf-turnstile|challenges\.cloudflare\.com)""", re.IGNORECASE),
            "Cloudflare Turnstile challenge detected",
        ),
        (
            re.compile(r"""(?:g-recaptcha|recaptcha/api\.js|recaptcha-anchor)""", re.IGNORECASE),
            "Google reCAPTCHA challenge detected",
        ),
        (
            re.compile(r"""(?:h-captcha|hcaptcha\.com)""", re.IGNORECASE),
            "hCaptcha challenge detected",
        ),
        (
            re.compile(r"""<iframe[^>]*src=['"][^'"]*captcha[^'"]*['"]""", re.IGNORECASE),
            "Generic embedded captcha iframe detected",
        ),
    )

    CONFIRM_SCREEN_SIGNATURES: tuple[tuple[re.Pattern[str], str], ...] = (
        (
            re.compile(
                r"""(?:data-testid=['"](?:confirm-(?:order|payment|purchase|transfer)|checkout-confirm)['"]|id=['"]confirm-payment['"])""",
                re.IGNORECASE,
            ),
            "High-stakes checkout or payment confirmation element detected",
        ),
        (
            re.compile(
                r"""(?:<div[^>]*role=['"]dialog['"][^>]*>.*?(?:confirm\s+(?:order|payment|deletion|subscription)|authorize\s+charge).*?</div>)""",
                re.IGNORECASE | re.DOTALL,
            ),
            "Modal confirmation dialog requesting user financial authorization",
        ),
        (
            re.compile(
                r"""(?:<button[^>]*class=['"][^'"]*(?:btn-danger|btn-confirm|confirm-action)[^'"]*['"][^>]*>.*?(?:confirm|authorize|pay\s+now).*?</button>)""",
                re.IGNORECASE | re.DOTALL,
            ),
            "Irreversible action confirmation button detected",
        ),
    )

    def __init__(self) -> None:
        self._pending_handoffs: dict[str, HandoffInterceptionResult] = {}

    def inspect_page(self, html_or_dom: str, url: str = "") -> HandoffInterceptionResult:
        """Inspect page DOM for captchas and confirmation screens, enforcing mandatory handoff."""
        interception_id = f"handoff-{uuid.uuid4().hex[:12]}"
        now = time.time()

        # 1. Check for anti-bot captchas
        for pattern, explanation in self.CAPTCHA_SIGNATURES:
            if pattern.search(html_or_dom):
                result = HandoffInterceptionResult(
                    interception_id=interception_id,
                    trigger_type=HandoffTriggerType.CAPTCHA_CHALLENGE,
                    matched_selector=pattern.pattern,
                    is_handoff_required=True,
                    explanation=f"Mandatory handoff: {explanation} on {url or 'active page'}",
                    is_resolved=False,
                    timestamp=now,
                )
                self._pending_handoffs[interception_id] = result
                logger.warning("Interception gate triggered (Captcha): %s", explanation)
                return result

        # 2. Check for irreversible confirm screens
        for pattern, explanation in self.CONFIRM_SCREEN_SIGNATURES:
            if pattern.search(html_or_dom):
                result = HandoffInterceptionResult(
                    interception_id=interception_id,
                    trigger_type=HandoffTriggerType.CONFIRM_SCREEN,
                    matched_selector=pattern.pattern,
                    is_handoff_required=True,
                    explanation=f"Mandatory handoff: {explanation} on {url or 'active page'}",
                    is_resolved=False,
                    timestamp=now,
                )
                self._pending_handoffs[interception_id] = result
                logger.warning("Interception gate triggered (Confirm Screen): %s", explanation)
                return result

        # 3. Safe to proceed autonomously
        return HandoffInterceptionResult(
            interception_id=interception_id,
            trigger_type=None,
            matched_selector="",
            is_handoff_required=False,
            explanation="Page evaluated safe. No captcha challenges or confirmation dialogs found.",
            is_resolved=True,
            timestamp=now,
        )

    def resolve_interception(self, interception_id: str) -> HandoffInterceptionResult:
        """Human operator confirms resolution of captcha or confirmation screen in browser."""
        pending = self._pending_handoffs.pop(interception_id, None)
        if pending is None:
            raise KeyError(f"Pending handoff interception '{interception_id}' not found.")

        resolved = HandoffInterceptionResult(
            interception_id=pending.interception_id,
            trigger_type=pending.trigger_type,
            matched_selector=pending.matched_selector,
            is_handoff_required=False,
            explanation=f"Handoff successfully resolved by human operator (originally: {pending.explanation})",
            is_resolved=True,
            timestamp=time.time(),
        )
        logger.info("Human operator resolved handoff interception %s", interception_id)
        return resolved

    def list_pending_interceptions(self) -> list[HandoffInterceptionResult]:
        """List all browser screens currently waiting for human intervention."""
        return list(self._pending_handoffs.values())
