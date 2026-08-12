"""Live integration tests for the real web_fetch engine chain.

The full crawl path is unmocked: SSRF/DNS-pin validation -> scrapling HTTP
fetch -> content pipeline. Requires the ``[web]`` extra (scrapling) in the
running interpreter — the server venv (``./myrm test``) has it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from myrm_agent_harness.core.security.http.secure_fetch import secure_get
from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine

_ENV_TEST = Path(__file__).resolve().parents[3] / "myrm-agent" / "myrm-agent-server" / ".env.test"


def _load_env_test() -> None:
    if not _ENV_TEST.exists():
        return
    for raw in _ENV_TEST.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env_test()


def _make_engine(tmpdir: str) -> FetchEngine:
    return FetchEngine(adaptive_router_rules_file=Path(tmpdir) / "rules.pkl")


class TestRealCrawl:
    @pytest.mark.asyncio
    async def test_crawl_public_url_returns_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            try:
                doc = await engine.crawl("https://example.com/", max_chars=2000)
                assert doc is not None
                assert doc.page_content.strip()
            finally:
                await engine.shutdown()

    @pytest.mark.asyncio
    async def test_crawl_respects_fail_cache_on_error(self) -> None:
        # 私有 IP 在 fetcher 之前被 SSRF 拦截，fail cache 不记录（不产生副作用）
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            try:
                doc = await engine.crawl("http://192.168.1.1/")
                assert doc is None
                assert await engine.crawl("http://192.168.1.1/") is None
            finally:
                await engine.shutdown()


class TestSecureGetRealHttp:
    @pytest.mark.asyncio
    async def test_secure_get_public_url_returns_200(self) -> None:
        response = await secure_get("https://example.com/", timeout=15.0)
        assert response.status_code == 200
        assert response.text.strip()
