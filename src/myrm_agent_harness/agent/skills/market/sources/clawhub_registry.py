"""ClawHub-compatible registry URL resolution and reachability probe.

[INPUT]
- Process env CLAWHUB_URL, CLAWHUB_REGISTRY, OPENCLAW_CLAWHUB_URL (OpenClaw parity)

[OUTPUT]
- resolve_registry_base_url: Effective registry base URL for ClawHubSource (CLAWHUB_URL SSOT)
- bootstrap_registry_env_from_legacy: One-shot migrate OpenClaw legacy env vars
- clear_shadow_registry_env: Remove CLAWHUB_REGISTRY / OPENCLAW_CLAWHUB_URL from process env
- migrate_legacy_registry_url: Rewrite known-bad persisted hosts
- probe_clawhub_registry: Strict ClawHub contract probe (dict JSON, not HTML or bare arrays)

[POS]
Protocol-level registry helpers for ClawHubSource. No server or UI dependencies.
"""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlparse

import httpx

from myrm_agent_harness.infra.tls_compat import create_httpx_client

logger = logging.getLogger(__name__)

CLAWHUB_DEFAULT_URL = "https://clawhub.ai"
CLAWHUB_CN_PRESET_URL = "https://skill.xfyun.cn"
LEGACY_CN_REGISTRY_HOSTS = frozenset({"skillhub.cn", "www.skillhub.cn"})

CLAWHUB_URL_ENV = "CLAWHUB_URL"
CLAWHUB_REGISTRY_ENV = "CLAWHUB_REGISTRY"
OPENCLAW_CLAWHUB_URL_ENV = "OPENCLAW_CLAWHUB_URL"

LEGACY_REGISTRY_ENV_NAMES = (
    CLAWHUB_REGISTRY_ENV,
    OPENCLAW_CLAWHUB_URL_ENV,
)

PROBE_TIMEOUT_SECONDS = 8.0


def clear_shadow_registry_env() -> None:
    """Remove legacy OpenClaw env vars so CLAWHUB_URL is the runtime SSOT."""
    for env_name in LEGACY_REGISTRY_ENV_NAMES:
        os.environ.pop(env_name, None)


def bootstrap_registry_env_from_legacy() -> None:
    """Migrate OpenClaw legacy env vars into CLAWHUB_URL once at process start."""
    if os.environ.get(CLAWHUB_URL_ENV, "").strip():
        return
    for env_name in LEGACY_REGISTRY_ENV_NAMES:
        raw = os.environ.get(env_name, "").strip().rstrip("/")
        if not raw:
            continue
        migrated = migrate_legacy_registry_url(raw)
        os.environ[CLAWHUB_URL_ENV] = migrated or CLAWHUB_DEFAULT_URL
        clear_shadow_registry_env()
        return


def migrate_legacy_registry_url(url: str) -> str:
    """Rewrite legacy marketing-site hosts to the ClawHub-compatible CN API."""
    value = url.strip().rstrip("/")
    if not value:
        return ""
    host = urlparse(value).netloc.lower()
    if host in LEGACY_CN_REGISTRY_HOSTS:
        return CLAWHUB_CN_PRESET_URL
    return value


def resolve_registry_base_url() -> str:
    """Resolve effective ClawHub registry base URL (CLAWHUB_URL SSOT at runtime)."""
    bootstrap_registry_env_from_legacy()
    raw = os.environ.get(CLAWHUB_URL_ENV, "").strip().rstrip("/")
    if raw:
        migrated = migrate_legacy_registry_url(raw)
        return migrated or CLAWHUB_DEFAULT_URL
    return CLAWHUB_DEFAULT_URL


def _response_is_clawhub_json(response: httpx.Response) -> tuple[bool, str]:
    content_type = response.headers.get("content-type", "").lower()
    if "application/json" not in content_type and not content_type.startswith("application/"):
        return False, "not_clawhub_json"

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return False, "not_clawhub_json"

    if isinstance(payload, dict):
        if "results" in payload:
            return True, "reachable"
        if "apiBase" in payload:
            return True, "reachable"
    return False, "invalid_clawhub_payload"


async def probe_clawhub_registry(base_url: str) -> tuple[bool, str]:
    """Return reachability for a ClawHub-compatible registry (strict JSON contract)."""
    normalized = migrate_legacy_registry_url(base_url.strip().rstrip("/"))
    if not normalized:
        normalized = CLAWHUB_DEFAULT_URL

    try:
        async with create_httpx_client(timeout=PROBE_TIMEOUT_SECONDS) as client:
            well_known = await client.get(f"{normalized}/.well-known/clawhub.json")
            if well_known.status_code == 200:
                ok, detail = _response_is_clawhub_json(well_known)
                if ok:
                    return True, detail

            search = await client.get(
                f"{normalized}/api/v1/search",
                params={"q": "*", "limit": "1"},
            )
            if search.status_code != 200:
                return False, f"HTTP {search.status_code}"
            return _response_is_clawhub_json(search)
    except httpx.TimeoutException:
        return False, "timeout"
    except Exception as exc:
        logger.warning("ClawHub registry probe failed for %s: %s", normalized, exc)
        return False, str(exc)


async def probe_configured_cn_mirror() -> tuple[bool, str]:
    return await probe_clawhub_registry(CLAWHUB_CN_PRESET_URL)
