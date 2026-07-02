"""CapSolver-based automatic CAPTCHA solver.

Implements the ``CaptchaSolver`` protocol using the CapSolver REST API.
Supports: reCAPTCHA v2/v3, hCaptcha, Cloudflare Turnstile/Challenge.

[INPUT]
- .protocols::CaptchaInfo, CaptchaSolveResult, CaptchaType (POS: data types)
- httpx (POS: async HTTP client)

[OUTPUT]
- ApiSolver: automatic CaptchaSolver implementation via CapSolver API

[POS]
Third-party API CAPTCHA solver for browser automation.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING

from .protocols import CaptchaInfo, CaptchaSolveResult, CaptchaType

if TYPE_CHECKING:
    from patchright.async_api import Page

logger = logging.getLogger(__name__)

_CAPSOLVER_BASE = "https://api.capsolver.com"
_CREATE_TASK_TIMEOUT = 10.0
_POLL_INTERVAL_S = 3.0
_MAX_POLL_ATTEMPTS = 30

_TASK_TYPE_MAP: dict[CaptchaType, str] = {
    CaptchaType.RECAPTCHA: "ReCaptchaV2TaskProxyLess",
    CaptchaType.HCAPTCHA: "HCaptchaTaskProxyLess",
    CaptchaType.CLOUDFLARE_TURNSTILE: "AntiTurnstileTaskProxyLess",
    CaptchaType.CLOUDFLARE_CHALLENGE: "AntiTurnstileTaskProxyLess",
}

_SITEKEY_PATTERNS: dict[CaptchaType, re.Pattern[str]] = {
    CaptchaType.RECAPTCHA: re.compile(
        r'data-sitekey=["\']([a-zA-Z0-9_-]{40})["\']', re.I
    ),
    CaptchaType.HCAPTCHA: re.compile(
        r'data-sitekey=["\']([a-f0-9-]{36,})["\']', re.I
    ),
    CaptchaType.CLOUDFLARE_TURNSTILE: re.compile(
        r'data-sitekey=["\']([a-zA-Z0-9_-]{30,})["\']', re.I
    ),
    CaptchaType.CLOUDFLARE_CHALLENGE: re.compile(
        r'data-sitekey=["\']([a-zA-Z0-9_-]{30,})["\']', re.I
    ),
}


class ApiSolver:
    """Automatic CAPTCHA solver using the CapSolver REST API.

    Thread-safety: stateless — safe for concurrent use.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def solve(
        self,
        captcha_info: CaptchaInfo,
        page: Page,
    ) -> CaptchaSolveResult:
        """Solve CAPTCHA via CapSolver createTask + getTaskResult."""
        start = time.monotonic()

        task_type = _TASK_TYPE_MAP.get(captcha_info.captcha_type)
        if not task_type:
            return CaptchaSolveResult(
                success=False,
                method="capsolver",
                elapsed_ms=(time.monotonic() - start) * 1000,
                message=f"Unsupported CAPTCHA type: {captcha_info.captcha_type.value}",
            )

        website_url = page.url
        website_key = await self._extract_sitekey(page, captcha_info.captcha_type)
        if not website_key:
            return CaptchaSolveResult(
                success=False,
                method="capsolver",
                elapsed_ms=(time.monotonic() - start) * 1000,
                message="Failed to extract website key from page HTML",
            )

        task_id = await self._create_task(task_type, website_url, website_key)
        if not task_id:
            return CaptchaSolveResult(
                success=False,
                method="capsolver",
                elapsed_ms=(time.monotonic() - start) * 1000,
                message="CapSolver createTask failed",
            )

        token = await self._poll_result(task_id)
        if not token:
            return CaptchaSolveResult(
                success=False,
                method="capsolver",
                elapsed_ms=(time.monotonic() - start) * 1000,
                message="CapSolver getTaskResult timed out or failed",
            )

        injected = await self._inject_token(page, token, captcha_info.captcha_type)
        elapsed_ms = (time.monotonic() - start) * 1000

        if injected:
            logger.info(
                "ApiSolver: CAPTCHA solved (type=%s, elapsed=%.0fms)",
                captcha_info.captcha_type.value,
                elapsed_ms,
            )
        return CaptchaSolveResult(
            success=injected,
            method="capsolver",
            elapsed_ms=elapsed_ms,
            message="" if injected else "Token injection failed",
        )

    async def _extract_sitekey(
        self, page: Page, captcha_type: CaptchaType
    ) -> str | None:
        """Extract the site key from page HTML using regex."""
        pattern = _SITEKEY_PATTERNS.get(captcha_type)
        if not pattern:
            return None
        try:
            html = await page.content()
        except Exception:
            return None
        match = pattern.search(html[:15_000])
        return match.group(1) if match else None

    async def _create_task(
        self,
        task_type: str,
        website_url: str,
        website_key: str,
    ) -> str | None:
        """Call CapSolver createTask and return the task ID."""
        from myrm_agent_harness.infra.tls_compat import create_httpx_client

        payload = {
            "clientKey": self._api_key,
            "task": {
                "type": task_type,
                "websiteURL": website_url,
                "websiteKey": website_key,
            },
        }
        try:
            async with create_httpx_client(timeout=_CREATE_TASK_TIMEOUT) as client:
                resp = await client.post(
                    f"{_CAPSOLVER_BASE}/createTask", json=payload
                )
                data = resp.json()
                if data.get("errorId", 1) == 0:
                    return data.get("taskId")
                logger.warning("CapSolver createTask error: %s", data.get("errorDescription"))
                return None
        except Exception as exc:
            logger.warning("CapSolver createTask request failed: %s", exc)
            return None

    async def _poll_result(self, task_id: str) -> str | None:
        """Poll CapSolver getTaskResult until ready or max attempts."""
        from myrm_agent_harness.infra.tls_compat import create_httpx_client

        payload = {"clientKey": self._api_key, "taskId": task_id}
        async with create_httpx_client(timeout=_CREATE_TASK_TIMEOUT) as client:
            for _ in range(_MAX_POLL_ATTEMPTS):
                await asyncio.sleep(_POLL_INTERVAL_S)
                try:
                    resp = await client.post(
                        f"{_CAPSOLVER_BASE}/getTaskResult", json=payload
                    )
                    data = resp.json()
                    status = data.get("status")
                    if status == "ready":
                        solution = data.get("solution", {})
                        return (
                            solution.get("gRecaptchaResponse")
                            or solution.get("token")
                            or solution.get("cf_clearance")
                        )
                    if status == "failed":
                        logger.warning("CapSolver task failed: %s", data.get("errorDescription"))
                        return None
                except Exception as exc:
                    logger.debug("CapSolver poll error: %s", exc)
                    continue
        return None

    async def _inject_token(
        self, page: Page, token: str, captcha_type: CaptchaType
    ) -> bool:
        """Inject the solved token into the page and trigger verification."""
        try:
            if captcha_type == CaptchaType.RECAPTCHA:
                await page.evaluate(
                    """(token) => {
                    const el = document.getElementById('g-recaptcha-response');
                    if (el) { el.value = token; el.style.display = 'block'; }
                    if (typeof ___grecaptcha_cfg !== 'undefined') {
                        Object.entries(___grecaptcha_cfg.clients).forEach(([k,v]) => {
                            const cb = v?.S?.S?.callback || v?.R?.R?.callback;
                            if (cb) cb(token);
                        });
                    }
                }""",
                    token,
                )
            elif captcha_type == CaptchaType.HCAPTCHA:
                await page.evaluate(
                    """(token) => {
                    const el = document.querySelector('[name="h-captcha-response"]');
                    if (el) el.value = token;
                    const iframe = document.querySelector('iframe[src*="hcaptcha"]');
                    if (iframe) {
                        const ev = new MessageEvent('message', {data: {type:'hcaptcha:solved', token}});
                        window.dispatchEvent(ev);
                    }
                }""",
                    token,
                )
            elif captcha_type in (
                CaptchaType.CLOUDFLARE_TURNSTILE,
                CaptchaType.CLOUDFLARE_CHALLENGE,
            ):
                await page.evaluate(
                    """(token) => {
                    const el = document.querySelector('[name="cf-turnstile-response"]');
                    if (el) el.value = token;
                    const cb = window.turnstile?.getResponse ? null :
                        document.querySelector('[data-callback]')?.getAttribute('data-callback');
                    if (cb && window[cb]) window[cb](token);
                }""",
                    token,
                )
            else:
                return False

            await asyncio.sleep(1.0)
            return True
        except Exception as exc:
            logger.warning("Token injection failed: %s", exc)
            return False
