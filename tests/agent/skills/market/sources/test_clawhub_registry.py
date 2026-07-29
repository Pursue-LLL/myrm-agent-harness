"""Unit tests for ClawHub registry resolver and strict probe."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from myrm_agent_harness.agent.skills.market.sources.clawhub_registry import (
    CLAWHUB_CN_PRESET_URL,
    CLAWHUB_DEFAULT_URL,
    CLAWHUB_REGISTRY_ENV,
    CLAWHUB_URL_ENV,
    OPENCLAW_CLAWHUB_URL_ENV,
    bootstrap_registry_env_from_legacy,
    clear_shadow_registry_env,
    migrate_legacy_registry_url,
    probe_clawhub_registry,
    probe_configured_cn_mirror,
    resolve_registry_base_url,
)


def test_migrate_legacy_empty_url() -> None:
    assert migrate_legacy_registry_url("") == ""
    assert migrate_legacy_registry_url("   ") == ""


def test_migrate_legacy_skillhub_cn_host() -> None:
    assert migrate_legacy_registry_url("https://skillhub.cn") == CLAWHUB_CN_PRESET_URL
    assert migrate_legacy_registry_url("https://www.skillhub.cn/") == CLAWHUB_CN_PRESET_URL
    assert migrate_legacy_registry_url("https://skill.xfyun.cn") == "https://skill.xfyun.cn"


def test_clear_shadow_registry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLAWHUB_REGISTRY_ENV, "https://example.com")
    monkeypatch.setenv(OPENCLAW_CLAWHUB_URL_ENV, "https://example.com")
    clear_shadow_registry_env()
    assert CLAWHUB_REGISTRY_ENV not in os.environ
    assert OPENCLAW_CLAWHUB_URL_ENV not in os.environ


def test_bootstrap_skips_when_clawhub_url_already_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLAWHUB_URL_ENV, "https://existing.example.com")
    monkeypatch.setenv(CLAWHUB_REGISTRY_ENV, "https://shadow.example.com")
    bootstrap_registry_env_from_legacy()
    assert os.environ.get(CLAWHUB_URL_ENV) == "https://existing.example.com"
    assert os.environ.get(CLAWHUB_REGISTRY_ENV) == "https://shadow.example.com"


def test_bootstrap_migrates_openclaw_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLAWHUB_URL_ENV, raising=False)
    monkeypatch.delenv(CLAWHUB_REGISTRY_ENV, raising=False)
    monkeypatch.setenv(OPENCLAW_CLAWHUB_URL_ENV, "https://openclaw.example.com")
    bootstrap_registry_env_from_legacy()
    assert os.environ.get(CLAWHUB_URL_ENV) == "https://openclaw.example.com"
    assert OPENCLAW_CLAWHUB_URL_ENV not in os.environ
    assert migrate_legacy_registry_url("https://skillhub.cn") == CLAWHUB_CN_PRESET_URL
    assert (
        migrate_legacy_registry_url("https://www.skillhub.cn/") == CLAWHUB_CN_PRESET_URL
    )
    assert (
        migrate_legacy_registry_url("https://skill.xfyun.cn")
        == "https://skill.xfyun.cn"
    )


def test_resolve_registry_base_url_prefers_clawhub_url_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CLAWHUB_URL_ENV, raising=False)
    monkeypatch.delenv(CLAWHUB_REGISTRY_ENV, raising=False)
    monkeypatch.setenv(CLAWHUB_URL_ENV, "https://registry.example.com")
    assert resolve_registry_base_url() == "https://registry.example.com"


def test_resolve_registry_base_url_falls_back_to_clawhub_registry_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CLAWHUB_URL_ENV, raising=False)
    monkeypatch.setenv(CLAWHUB_REGISTRY_ENV, "https://registry.example.com")
    assert resolve_registry_base_url() == "https://registry.example.com"
    assert os.environ.get(CLAWHUB_URL_ENV) == "https://registry.example.com"
    assert CLAWHUB_REGISTRY_ENV not in os.environ


def test_bootstrap_migrates_legacy_env_without_clawhub_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CLAWHUB_URL_ENV, raising=False)
    monkeypatch.delenv(CLAWHUB_REGISTRY_ENV, raising=False)
    monkeypatch.setenv(CLAWHUB_REGISTRY_ENV, "https://registry.example.com")
    bootstrap_registry_env_from_legacy()
    assert os.environ.get(CLAWHUB_URL_ENV) == "https://registry.example.com"
    assert CLAWHUB_REGISTRY_ENV not in os.environ


def test_resolve_registry_base_url_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CLAWHUB_URL_ENV, raising=False)
    monkeypatch.delenv(CLAWHUB_REGISTRY_ENV, raising=False)
    assert resolve_registry_base_url() == CLAWHUB_DEFAULT_URL


@pytest.mark.asyncio
async def test_probe_rejects_html_200() -> None:
    html_response = MagicMock()
    html_response.status_code = 200
    html_response.headers = {"content-type": "text/html"}
    html_response.json.side_effect = json.JSONDecodeError("not json", "", 0)

    search_response = MagicMock()
    search_response.status_code = 200
    search_response.headers = {"content-type": "text/html"}
    search_response.json.side_effect = json.JSONDecodeError("not json", "", 0)

    well_known_response = MagicMock()
    well_known_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[well_known_response, search_response],
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "myrm_agent_harness.agent.skills.market.sources.clawhub_registry.create_httpx_client",
        return_value=mock_client,
    ):
        reachable, detail = await probe_clawhub_registry("https://skillhub.cn")

    assert reachable is False
    assert detail == "not_clawhub_json"


@pytest.mark.asyncio
async def test_probe_accepts_json_results() -> None:
    search_response = MagicMock()
    search_response.status_code = 200
    search_response.headers = {"content-type": "application/json"}
    search_response.json.return_value = {"results": [{"slug": "demo"}]}

    well_known_response = MagicMock()
    well_known_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[well_known_response, search_response],
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "myrm_agent_harness.agent.skills.market.sources.clawhub_registry.create_httpx_client",
        return_value=mock_client,
    ):
        reachable, detail = await probe_clawhub_registry("https://skill.xfyun.cn")

    assert reachable is True
    assert detail == "reachable"


@pytest.mark.asyncio
async def test_probe_rejects_bare_json_list() -> None:
    search_response = MagicMock()
    search_response.status_code = 200
    search_response.headers = {"content-type": "application/json"}
    search_response.json.return_value = []

    well_known_response = MagicMock()
    well_known_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[well_known_response, search_response],
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "myrm_agent_harness.agent.skills.market.sources.clawhub_registry.create_httpx_client",
        return_value=mock_client,
    ):
        reachable, detail = await probe_clawhub_registry("https://skill.xfyun.cn")

    assert reachable is False
    assert detail == "invalid_clawhub_payload"


@pytest.mark.asyncio
async def test_probe_accepts_well_known_api_base() -> None:
    well_known_response = MagicMock()
    well_known_response.status_code = 200
    well_known_response.headers = {"content-type": "application/json"}
    well_known_response.json.return_value = {"apiBase": "/api/v1"}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=well_known_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "myrm_agent_harness.agent.skills.market.sources.clawhub_registry.create_httpx_client",
        return_value=mock_client,
    ):
        reachable, detail = await probe_clawhub_registry("")

    assert reachable is True
    assert detail == "reachable"


@pytest.mark.asyncio
async def test_probe_search_http_error() -> None:
    well_known_response = MagicMock()
    well_known_response.status_code = 404

    search_response = MagicMock()
    search_response.status_code = 503

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[well_known_response, search_response],
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "myrm_agent_harness.agent.skills.market.sources.clawhub_registry.create_httpx_client",
        return_value=mock_client,
    ):
        reachable, detail = await probe_clawhub_registry("https://skill.xfyun.cn")

    assert reachable is False
    assert detail == "HTTP 503"


@pytest.mark.asyncio
async def test_probe_timeout() -> None:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "myrm_agent_harness.agent.skills.market.sources.clawhub_registry.create_httpx_client",
        return_value=mock_client,
    ):
        reachable, detail = await probe_clawhub_registry("https://skill.xfyun.cn")

    assert reachable is False
    assert detail == "timeout"


@pytest.mark.asyncio
async def test_probe_unexpected_exception() -> None:
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("network down"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "myrm_agent_harness.agent.skills.market.sources.clawhub_registry.create_httpx_client",
        return_value=mock_client,
    ):
        reachable, detail = await probe_clawhub_registry("https://skill.xfyun.cn")

    assert reachable is False
    assert detail == "network down"


@pytest.mark.asyncio
async def test_probe_configured_cn_mirror_delegates() -> None:
    with patch(
        "myrm_agent_harness.agent.skills.market.sources.clawhub_registry.probe_clawhub_registry",
        new=AsyncMock(return_value=(True, "reachable")),
    ) as probe:
        reachable, detail = await probe_configured_cn_mirror()

    probe.assert_awaited_once_with(CLAWHUB_CN_PRESET_URL)
    assert reachable is True
    assert detail == "reachable"


@pytest.mark.asyncio
async def test_probe_rejects_invalid_dict_payload() -> None:
    search_response = MagicMock()
    search_response.status_code = 200
    search_response.headers = {"content-type": "application/json"}
    search_response.json.return_value = {"unexpected": True}

    well_known_response = MagicMock()
    well_known_response.status_code = 404

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(
        side_effect=[well_known_response, search_response],
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "myrm_agent_harness.agent.skills.market.sources.clawhub_registry.create_httpx_client",
        return_value=mock_client,
    ):
        reachable, detail = await probe_clawhub_registry("https://skill.xfyun.cn")

    assert reachable is False
    assert detail == "invalid_clawhub_payload"
