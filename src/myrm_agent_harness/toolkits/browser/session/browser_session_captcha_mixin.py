"""BrowserSession CAPTCHA detection and coordination.

[INPUT]
- captcha::detect_captcha, CaptchaHandleResult (POS: blocking CAPTCHA detection and structured result)
- self._captcha_coordinator (POS: solver coordination, provided by the BrowserSession aggregate root)

[OUTPUT]
- BrowserSessionCaptchaMixin: _handle_captcha_if_detected

[POS]
CAPTCHA step of BrowserSession navigation, called after navigate() and after click/dblclick
interactions. Inherited by BrowserSessionNavigationMixin, so it sits right after the tab mixin in
the MRO and before BrowserSessionLifecycleMixin.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.browser.captcha.protocols import CaptchaHandleResult


class BrowserSessionCaptchaMixin:
    async def _handle_captcha_if_detected(self) -> CaptchaHandleResult | None:
        """Detect and handle blocking CAPTCHAs on the current page.

        Called after navigate() and after click/dblclick interactions.

        Returns:
            Structured result if a CAPTCHA was detected, otherwise ``None``.
        """
        if self._captcha_coordinator is None:
            return None

        from myrm_agent_harness.toolkits.browser.captcha import detect_captcha

        page = self._tab_controller.get_active_page()
        captcha_info = await detect_captcha(page)

        if captcha_info is None or not captcha_info.blocking:
            return None

        solve_result = await self._captcha_coordinator.handle_captcha(
            captcha_info,
            page,
            is_managed=self.is_browser_managed(),
        )
        self._captcha_coordinator.reset()

        if solve_result.success:
            return CaptchaHandleResult(
                success=True,
                challenge_type=captcha_info.captcha_type.value,
                message=f"CAPTCHA resolved ({captcha_info.captcha_type.value}) via {solve_result.method}",
            )
        return CaptchaHandleResult(
            success=False,
            challenge_type=captcha_info.captcha_type.value,
            message=f"CAPTCHA not resolved ({captcha_info.reason}): {solve_result.message}",
        )
