"""Integration tests — encrypted session persistence end-to-end.

Exercises the FULL login-state roundtrip against a real Chromium instance
(patchright) and a real on-disk SessionVault:

1. Navigate a local HTTP page → plant a cookie + localStorage entry
2. ``save_session`` → encrypted ``.enc`` artifact lands on disk (non-plaintext)
3. Tear down the session → fresh ``BrowserSession`` restores the same vault
4. Navigate again → both cookie and localStorage are back
5. Session-memory bridge hook updates the real MemoryManager profile attribute

No mocking of the browser, vault, or persistence path — only the HTTP origin is
synthetic (loopback) so the suite is fully offline.

Run with: pytest -m integration tests/toolkits/browser/test_session_persistence_integration.py
"""

from __future__ import annotations

import asyncio
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.session.session_memory_bridge import (
    SessionMemoryBridge,
)
from myrm_agent_harness.toolkits.browser.session_vault import SessionVault
from myrm_agent_harness.toolkits.browser.session_vault.backends import FileVaultBackend
from myrm_agent_harness.toolkits.browser.session_vault.backends.file_backend import (
    load_or_create_key,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.relational import SQLiteRelationalStore

_PAGE_HTML = b"""<!DOCTYPE html>
<html>
<body>
    <h1>Session Persistence Integration</h1>
</body>
</html>
"""


class _QuietHandler(BaseHTTPRequestHandler):
    """Minimal handler that never writes access logs to keep output clean."""

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_PAGE_HTML)))
        self.end_headers()
        self.wfile.write(_PAGE_HTML)


@pytest.fixture(scope="module")
def http_origin() -> str:
    """Threaded loopback HTTP server serving a minimal HTML page."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
async def browser_pool() -> GlobalBrowserPool:
    """Real browser pool — one Chromium, warmed up once for the whole module."""
    pool = GlobalBrowserPool(max_browsers=1)
    await pool.warmup(browsers=1, pages_per_context=2)
    yield pool
    await pool.shutdown()


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return tmp_path / "session_vault"


@pytest.fixture
def vault_key(tmp_path: Path) -> bytes:
    return load_or_create_key(tmp_path / "vault.key")


@pytest.fixture
def session_vault(vault_dir: Path, vault_key: bytes) -> SessionVault:
    return SessionVault(FileVaultBackend(vault_dir), vault_key)


async def _plant_state(session: BrowserSession, origin: str) -> None:
    """Navigate and plant a cookie + localStorage entry on the page."""
    await session.new_tab(origin)
    await session.evaluate(
        "document.cookie = 'integ_cookie=hello; path=/'"
    )
    await session.evaluate("localStorage.setItem('integ_key', 'world')")


async def _read_state(session: BrowserSession, origin: str) -> tuple[str, str]:
    """Navigate and read back cookie + localStorage from the page."""
    await session.new_tab(origin)
    cookie = await session.evaluate("document.cookie")
    local = await session.evaluate("localStorage.getItem('integ_key')")
    return str(cookie), str(local)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_encrypted_save_restore_roundtrip(
    browser_pool: GlobalBrowserPool,
    session_vault: SessionVault,
    vault_dir: Path,
    http_origin: str,
) -> None:
    """Cookie + localStorage survive a full save → new session → restore cycle."""
    first = BrowserSession(
        browser_pool,
        ContextType.AGENT,
        session_vault=session_vault,
        allow_private_networks=True,
    )
    try:
        await _plant_state(first, http_origin)
        result = await first.save_session("127.0.0.1")
        assert "Saved encrypted session" in result
        assert "1 cookies" in result
        assert "1 localStorage items" in result
    finally:
        await first.close()

    enc_files = list(vault_dir.glob("*.enc"))
    assert len(enc_files) == 1
    raw = enc_files[0].read_bytes()
    assert raw[:12] != b"hello"  # header is 12-byte GCM nonce, not plaintext
    assert b"integ_cookie" not in raw
    assert b"world" not in raw
    assert b"127.0.0.1" not in raw

    second = BrowserSession(
        browser_pool,
        ContextType.AGENT,
        session_vault=session_vault,
        allow_private_networks=True,
    )
    try:
        await second.new_tab("about:blank")
        restored = await second.restore_session("127.0.0.1")
        assert "Restored encrypted session" in restored
        cookie, local = await _read_state(second, http_origin)
        assert "integ_cookie=hello" in cookie
        assert local == "world"
    finally:
        await second.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_save_invalid_domain_rejected(
    browser_pool: GlobalBrowserPool,
    session_vault: SessionVault,
    vault_dir: Path,
    http_origin: str,
) -> None:
    """Path-traversal domain names are rejected before touching the vault."""
    session = BrowserSession(
        browser_pool,
        ContextType.AGENT,
        session_vault=session_vault,
        allow_private_networks=True,
    )
    try:
        await _plant_state(session, http_origin)
        result = await session.save_session("../../etc/passwd")
        assert result.startswith("Error: Invalid domain name")
        assert list(vault_dir.glob("*.enc")) == []
    finally:
        await session.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_list_and_delete_sessions(
    browser_pool: GlobalBrowserPool,
    session_vault: SessionVault,
    vault_dir: Path,
    http_origin: str,
) -> None:
    """list_sessions surfaces saved domains; delete removes the artifact."""
    session = BrowserSession(
        browser_pool,
        ContextType.AGENT,
        session_vault=session_vault,
        allow_private_networks=True,
    )
    try:
        await _plant_state(session, http_origin)
        await session.save_session("127.0.0.1")

        listing = await session.list_sessions()
        assert "127.0.0.1" in listing

        deleted = await session.delete_session("127.0.0.1")
        assert "Deleted encrypted session" in deleted
        assert list(vault_dir.glob("*.enc")) == []

        listing_after = await session.list_sessions()
        assert "127.0.0.1" not in listing_after
    finally:
        await session.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_memory_bridge_hook_updates_real_profile(
    browser_pool: GlobalBrowserPool,
    session_vault: SessionVault,
    tmp_path: Path,
    http_origin: str,
) -> None:
    """save_session fires the lifecycle hook → MemoryManager profile reflects it."""
    relational = SQLiteRelationalStore(str(tmp_path / "memory.db"))
    try:
        manager = MemoryManager(
            MemoryConfig(embedding_model="test-model"),
            user_id="integration-user",
            relational=relational,
        )
        bridge = SessionMemoryBridge(manager)

        session = BrowserSession(
            browser_pool,
            ContextType.AGENT,
            session_vault=session_vault,
            allow_private_networks=True,
        )
        try:
            session.set_session_lifecycle_hook(bridge)
            await _plant_state(session, http_origin)
            result = await session.save_session("127.0.0.1")
            assert "Saved encrypted session" in result

            for _ in range(50):
                profile = await manager.get_profile_attribute(
                    "active_browser_sessions"
                )
                if profile and "127.0.0.1" in profile:
                    break
                await asyncio.sleep(0.1)
            assert profile and "127.0.0.1" in profile

            await session.delete_session("127.0.0.1")
            for _ in range(50):
                profile = await manager.get_profile_attribute(
                    "active_browser_sessions"
                )
                if not profile or "127.0.0.1" not in profile:
                    break
                await asyncio.sleep(0.1)
            assert not profile or "127.0.0.1" not in profile
        finally:
            await session.close()
    finally:
        await relational.close()
