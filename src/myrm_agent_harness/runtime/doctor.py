"""Global Doctor - Concurrent Diagnostics for Myrm Agent Harness.

[POS]
Concurrent diagnostic engine. Async-parallel model for significantly reduced environment check latency.

"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from functools import lru_cache
from types import ModuleType
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.browser.doctor import (
    CheckStatus,
    DoctorCheckResult,
    DoctorReport,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.doctor import CheckStatus

logger = logging.getLogger(__name__)

REQUIRED_PYTHON_VERSION = (3, 13)


@lru_cache(maxsize=128)
def _cached_find_spec(name: str) -> ModuleType | None:
    return importlib.util.find_spec(name)


@lru_cache(maxsize=128)
def _get_module_version(import_name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(import_name.replace("_", "-"))
    except Exception:
        try:
            mod = __import__(import_name)
            return getattr(mod, "__version__", None)
        except Exception:
            return None


class Doctor:
    """The diagnostic engine managing parallel check execution."""

    def __init__(self):
        self._tasks: list[Callable[[], Awaitable[DoctorCheckResult | list[DoctorCheckResult]]]] = []
        self._setup_default_tasks()

    def _setup_default_tasks(self) -> None:
        self._tasks.extend(
            [
                self._check_python,
                self._check_core_deps,
                self._check_optional_deps,
                self._check_llm_config,
                self._check_deploy_mode,
            ]
        )

    async def run(self, include_browser: bool = True, include_llm_test: bool = False) -> DoctorReport:
        """Execute all diagnostics in parallel."""
        # 1. Gather all base results
        pending = [t() for t in self._tasks]

        if include_browser:
            pending.append(self._check_system_resources())
            pending.append(self._check_browser_suite())

        if include_llm_test:
            pending.append(self._check_llm_connectivity())

        # 2. Parallel execution
        raw_results = await asyncio.gather(*pending, return_exceptions=True)

        # 3. Flaten and filter results
        checks: dict[str, DoctorCheckResult] = {}
        for res in raw_results:
            if isinstance(res, Exception):
                logger.error("Diagnostic task failed: %s", res)
                continue
            if isinstance(res, list):
                for item in res:
                    checks[item.name] = item
            else:
                checks[res.name] = res

        # 4. Generate report summary
        return self._build_report(checks)

    def _build_report(self, checks: dict[str, DoctorCheckResult]) -> DoctorReport:
        ok = sum(1 for c in checks.values() if c.status == CheckStatus.OK)
        warn = sum(1 for c in checks.values() if c.status == CheckStatus.WARNING)
        err = sum(1 for c in checks.values() if c.status == CheckStatus.ERROR)

        summary = f"{ok}/{len(checks)} passed"
        if warn:
            summary += f", {warn} warnings"
        if err:
            summary += f", {err} errors"

        recs = [c.fix for c in checks.values() if c.fix and c.status in (CheckStatus.ERROR, CheckStatus.MISSING)]
        return DoctorReport(
            checks=checks, summary=summary, overall_healthy=(err == 0), recommendations=list(dict.fromkeys(recs))
        )

    async def _check_python(self) -> DoctorCheckResult:
        v = sys.version_info
        v_str = f"{v[0]}.{v[1]}.{v[2]}"
        status = CheckStatus.OK if v[:2] >= REQUIRED_PYTHON_VERSION else CheckStatus.ERROR
        return DoctorCheckResult(
            "python", status, f"Python {v_str}", fix=None if status == CheckStatus.OK else "Update to 3.13+"
        )

    async def _check_core_deps(self) -> DoctorCheckResult:
        deps = ["langchain_core", "langgraph", "litellm", "pydantic"]
        missing = [d for d in deps if _cached_find_spec(d) is None]
        if missing:
            return DoctorCheckResult("core_deps", CheckStatus.ERROR, f"Missing: {', '.join(missing)}", fix="uv sync")
        return DoctorCheckResult("core_deps", CheckStatus.OK, "Core dependencies OK")

    async def _check_optional_deps(self) -> list[DoctorCheckResult]:
        optionals = [("patchright", "browser"), ("psutil", "monitoring"), ("jieba", "retrieval")]
        results = []
        for mod, extra in optionals:
            spec = _cached_find_spec(mod)
            results.append(
                DoctorCheckResult(
                    f"opt_{mod}",
                    CheckStatus.OK if spec else CheckStatus.WARNING,
                    f"{mod} {'OK' if spec else 'missing'}",
                    fix=None if spec else f"uv sync --extra {extra}",
                )
            )
        return results

    async def _check_llm_config(self) -> DoctorCheckResult:
        m = os.getenv("MYRM_MODEL_NAME")
        k = os.getenv("MYRM_API_KEY")
        if not m or not k:
            return DoctorCheckResult("llm_config", CheckStatus.ERROR, "LLM env vars missing", fix="Set MYRM_API_KEY")
        return DoctorCheckResult("llm_config", CheckStatus.OK, f"LLM Configured ({m})")

    async def _check_deploy_mode(self) -> DoctorCheckResult:
        """Check deployment mode configuration and mode-specific requirements."""
        try:
            deploy_mode = os.getenv("DEPLOY_MODE", "local").lower()
            webui_mode = os.getenv("WEBUI_MODE", "false").lower()
            webui_remote = os.getenv("WEBUI_REMOTE_MODE", "false").lower()

            mode_desc = f"DEPLOY_MODE={deploy_mode}"
            if webui_mode == "true":
                mode_desc += ", WebUI"
                if webui_remote == "true":
                    mode_desc += " Remote"

            if deploy_mode == "sandbox":
                # Sandbox mode: check SANDBOX_API_KEY
                sandbox_key = os.getenv("SANDBOX_API_KEY")
                if not sandbox_key:
                    return DoctorCheckResult(
                        "deploy_mode", CheckStatus.ERROR,
                        f"{mode_desc} — SANDBOX_API_KEY missing",
                        fix="Set SANDBOX_API_KEY for sandbox mode"
                    )
                return DoctorCheckResult("deploy_mode", CheckStatus.OK, mode_desc)

            if webui_remote == "true":
                # WebUI Remote: check SANDBOX_API_KEY for auth
                sandbox_key = os.getenv("SANDBOX_API_KEY")
                if not sandbox_key:
                    return DoctorCheckResult(
                        "deploy_mode", CheckStatus.WARNING,
                        f"{mode_desc} — SANDBOX_API_KEY not set, remote access unsecured",
                        fix="Set SANDBOX_API_KEY to secure remote access"
                    )

            return DoctorCheckResult("deploy_mode", CheckStatus.OK, mode_desc)
        except Exception as e:
            return DoctorCheckResult("deploy_mode", CheckStatus.WARNING, f"Deploy mode check failed: {e}")

    async def _check_llm_connectivity(self) -> DoctorCheckResult:
        """Lightweight HTTP probe to LLM provider endpoint.

        Uses HTTP HEAD instead of actual LLM call to avoid token consumption
        and reduce latency from 2-5s to <1s.
        """
        try:
            import httpx
            import litellm

            model = os.getenv("MYRM_MODEL_NAME", "")
            if not model:
                return DoctorCheckResult("llm_conn", CheckStatus.ERROR, "No LLM model configured")

            # Get the base URL for the model's provider
            try:
                _, _, api_base, _ = litellm.get_llm_provider(model=model)
            except Exception:
                api_base = None

            # Determine probe URL
            if api_base:
                probe_url = api_base.rstrip("/")
            else:
                # Default OpenAI-compatible endpoint
                probe_url = "https://api.openai.com/v1"

            # Lightweight HEAD probe with 5s timeout
            async with httpx.AsyncClient(timeout=5.0) as client:
                try:
                    resp = await client.head(probe_url, follow_redirects=True)
                    # 2xx, 401, 403 all indicate the endpoint is reachable
                    if resp.status_code < 500:
                        return DoctorCheckResult(
                            "llm_conn", CheckStatus.OK,
                            f"LLM endpoint reachable ({probe_url}, HTTP {resp.status_code})"
                        )
                    return DoctorCheckResult(
                        "llm_conn", CheckStatus.WARNING,
                        f"LLM endpoint returned HTTP {resp.status_code}"
                    )
                except httpx.ConnectError as e:
                    return DoctorCheckResult(
                        "llm_conn", CheckStatus.ERROR,
                        f"LLM endpoint unreachable: {str(e)[:80]}"
                    )
        except ImportError:
            # Fallback to full LLM call if httpx not available
            try:
                import litellm

                await litellm.acompletion(
                    model=os.getenv("MYRM_MODEL_NAME", ""),
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1,
                )
                return DoctorCheckResult("llm_conn", CheckStatus.OK, "LLM Connectivity OK")
            except Exception as e:
                return DoctorCheckResult("llm_conn", CheckStatus.ERROR, f"LLM Conn failed: {str(e)[:100]}")
        except Exception as e:
            return DoctorCheckResult("llm_conn", CheckStatus.ERROR, f"LLM probe failed: {str(e)[:100]}")

    async def _check_system_resources(self) -> list[DoctorCheckResult]:
        from myrm_agent_harness.toolkits.browser.doctor import _check_disk, _check_memory

        return [_check_memory(), _check_disk()]

    async def _check_browser_suite(self) -> list[DoctorCheckResult]:
        try:
            from myrm_agent_harness.toolkits.browser.doctor import run_doctor

            rep = await run_doctor(include_launch_test=False)
            return [c for c in rep.checks.values() if c.name not in ("memory", "disk")]
        except Exception as e:
            return [DoctorCheckResult("browser_suite", CheckStatus.WARNING, f"Browser diag failed: {e}")]


def format_global_report(report: DoctorReport) -> str:
    from myrm_agent_harness.runtime.doctor_cli import format_styled_report

    return format_styled_report(report)


async def run_global_doctor(**kwargs) -> DoctorReport:
    """Convenience bridge for backward compatibility."""
    return await Doctor().run(
        include_browser=kwargs.get("include_browser", True), include_llm_test=kwargs.get("include_llm_test", False)
    )


async def _async_main():
    rep = await Doctor().run(include_llm_test="--test-llm" in sys.argv)
    from myrm_agent_harness.runtime.doctor_cli import format_styled_report

    print(format_styled_report(rep))
    return 0 if rep.overall_healthy else 1


def main():
    return asyncio.run(_async_main())


if __name__ == "__main__":
    sys.exit(main())
