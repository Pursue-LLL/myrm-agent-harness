"""Tests for MCP client management (target building, auth injection, TLS/mTLS)."""

from __future__ import annotations

import datetime
import ssl
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.mcp.client import MCPClientManager


@dataclass
class FakeMCPServerConfig:
    """Minimal stub satisfying MCPServerConfigProtocol."""

    name: str = "test-server"
    type: str = "sse"
    url: str | None = "https://example.com/mcp"
    command: str | None = None
    args: list[str] | None = None
    description: str = "Test server"
    headers: dict[str, str] | None = None
    extra_params: dict[str, object] | None = None
    required_secrets: list[str] | None = None
    tool_include: list[str] | None = None
    tool_exclude: list[str] | None = None
    host_serial: bool = False
    connect_timeout: float = 15.0
    execute_timeout: float = 120.0
    keepalive_interval: float | None = None
    ssl_verify: bool | str | None = None
    client_cert: str | None = None
    client_key: str | None = None
    client_key_password: str | None = None
    auth_provider: object | None = None


@pytest.fixture(scope="module")
def tls_certs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Generate a self-signed cert plus plain/encrypted keys for mTLS tests."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    tmp = tmp_path_factory.mktemp("mcp_tls")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mcp-test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    enc_key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.BestAvailableEncryption(b"s3cr3t"),
    )

    paths = {
        "cert": tmp / "client.crt",
        "key": tmp / "client.key",
        "enc_key": tmp / "client.enc.key",
        "bundle": tmp / "bundle.pem",
        "ca": tmp / "ca.pem",
    }
    paths["cert"].write_bytes(cert_pem)
    paths["key"].write_bytes(key_pem)
    paths["enc_key"].write_bytes(enc_key_pem)
    paths["bundle"].write_bytes(cert_pem + key_pem)
    paths["ca"].write_bytes(cert_pem)  # self-signed cert doubles as its own CA bundle

    ca_dir = tmp / "ca_dir"  # OpenSSL capath-style directory of CA certs
    ca_dir.mkdir()
    (ca_dir / "ca.pem").write_bytes(cert_pem)
    paths["ca_dir"] = ca_dir

    return {**{k: str(v) for k, v in paths.items()}, "passphrase": "s3cr3t"}


class TestBuildClientTarget:
    """build_client_target: transport target construction."""

    def test_sse_returns_url(self) -> None:
        cfg = FakeMCPServerConfig(type="sse", url="https://api.example.com/sse")
        target = MCPClientManager.build_client_target(cfg)
        assert target == "https://api.example.com/sse"

    def test_streamable_http_returns_url(self) -> None:
        cfg = FakeMCPServerConfig(type="streamable_http", url="https://api.example.com/http")
        target = MCPClientManager.build_client_target(cfg)
        assert target == "https://api.example.com/http"

    def test_stdio_returns_params(self) -> None:
        from mcp import StdioServerParameters

        cfg = FakeMCPServerConfig(
            type="stdio",
            url=None,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
        )
        target = MCPClientManager.build_client_target(cfg)
        assert isinstance(target, StdioServerParameters)
        assert target.command == "npx"
        assert target.args == ["-y", "@modelcontextprotocol/server-filesystem"]

    def test_stdio_no_args(self) -> None:
        from mcp import StdioServerParameters

        cfg = FakeMCPServerConfig(type="stdio", url=None, command="mcp-server", args=None)
        target = MCPClientManager.build_client_target(cfg)
        assert isinstance(target, StdioServerParameters)
        assert target.args == []

    def test_stdio_reads_env_cwd_from_extra_params(self) -> None:
        from mcp import StdioServerParameters

        cfg = FakeMCPServerConfig(
            type="stdio",
            url=None,
            command="python",
            args=["server.py"],
            extra_params={
                "env": {"API_KEY": "abc", "EMPTY": ""},
                "cwd": "/srv/workdir",
            },
        )
        target = MCPClientManager.build_client_target(cfg)
        assert isinstance(target, StdioServerParameters)
        assert target.env == {"API_KEY": "abc"}
        assert target.cwd == "/srv/workdir"

    def test_stdio_expands_plugin_placeholders(self) -> None:
        from mcp import StdioServerParameters

        cfg = FakeMCPServerConfig(
            type="stdio",
            url=None,
            command="./bin/pdf",
            args=["--data", "${PLUGIN_DATA}/cache", "--keep", "${OTHER_VAR}"],
            extra_params={
                "plugin_root": "/data/plugins/demo-plugin",
                "data_root": "/data/plugins/demo-plugin_data",
                "cwd": "./",
            },
        )
        target = MCPClientManager.build_client_target(cfg)
        assert isinstance(target, StdioServerParameters)
        # Command is a plugin-relative path, never placeholder-expanded (§7.2.1).
        assert target.command == "./bin/pdf"
        assert target.args == [
            "--data",
            "/data/plugins/demo-plugin_data/cache",
            # Unknown placeholders are never substituted or dropped.
            "--keep",
            "${OTHER_VAR}",
        ]
        # A "./" cwd with a configured plugin root resolves to the root itself.
        assert target.cwd == "/data/plugins/demo-plugin"

    def test_stdio_no_extra_params_keeps_null_env_cwd(self) -> None:
        from mcp import StdioServerParameters

        cfg = FakeMCPServerConfig(type="stdio", url=None, command="mcp-server", args=None)
        target = MCPClientManager.build_client_target(cfg)
        assert isinstance(target, StdioServerParameters)
        assert target.env is None
        assert target.cwd is None

    def test_unsupported_type_raises(self) -> None:
        cfg = FakeMCPServerConfig(type="websocket")
        with pytest.raises(ValueError, match="Unsupported transport type"):
            MCPClientManager.build_client_target(cfg)

    def test_http_missing_url_raises(self) -> None:
        cfg = FakeMCPServerConfig(type="sse", url=None)
        with pytest.raises(ValueError, match="requires 'url'"):
            MCPClientManager.build_client_target(cfg)


class TestInjectAuthHeaders:
    """_inject_auth_headers_into_config: OAuth/auth header injection for HTTP transports."""

    @pytest.mark.asyncio
    async def test_no_auth_provider(self) -> None:
        cfg = FakeMCPServerConfig(auth_provider=None)
        await MCPClientManager._inject_auth_headers_into_config(cfg)
        assert not hasattr(cfg, "_injected_auth_headers")

    @pytest.mark.asyncio
    async def test_stdio_skips_auth(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer token"})
        cfg = FakeMCPServerConfig(type="stdio", auth_provider=provider)
        await MCPClientManager._inject_auth_headers_into_config(cfg)
        provider.get_auth_headers.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sse_injects_headers(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer abc123"})
        cfg = FakeMCPServerConfig(auth_provider=provider)
        await MCPClientManager._inject_auth_headers_into_config(cfg)
        headers = MCPClientManager.get_headers(cfg)
        assert headers["Authorization"] == "Bearer abc123"

    @pytest.mark.asyncio
    async def test_streamable_http_injects_headers(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={"X-Api-Key": "key123"})
        cfg = FakeMCPServerConfig(type="streamable_http", auth_provider=provider)
        await MCPClientManager._inject_auth_headers_into_config(cfg)
        headers = MCPClientManager.get_headers(cfg)
        assert headers["X-Api-Key"] == "key123"

    @pytest.mark.asyncio
    async def test_merges_with_existing_headers(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer new"})
        cfg = FakeMCPServerConfig(
            auth_provider=provider,
            headers={"X-Existing": "keep"},
        )
        await MCPClientManager._inject_auth_headers_into_config(cfg)
        headers = MCPClientManager.get_headers(cfg)
        assert headers == {"X-Existing": "keep", "Authorization": "Bearer new"}

    @pytest.mark.asyncio
    async def test_empty_auth_headers_skips(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={})
        cfg = FakeMCPServerConfig(auth_provider=provider)
        await MCPClientManager._inject_auth_headers_into_config(cfg)
        assert not hasattr(cfg, "_injected_auth_headers")

    @pytest.mark.asyncio
    async def test_auth_failure_is_non_fatal(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(side_effect=RuntimeError("Token expired"))
        cfg = FakeMCPServerConfig(auth_provider=provider)
        await MCPClientManager._inject_auth_headers_into_config(cfg)
        assert not hasattr(cfg, "_injected_auth_headers")


class TestPrepareServerConfigs:
    """prepare_server_configs: multi-server config validation."""

    @pytest.mark.asyncio
    async def test_valid_config_passes(self) -> None:
        cfg = FakeMCPServerConfig(name="my-sse", type="sse", url="https://example.com/sse")
        result = await MCPClientManager.prepare_server_configs([cfg])
        assert "my-sse" in result

    @pytest.mark.asyncio
    async def test_config_error_skips_server(self) -> None:
        cfg = FakeMCPServerConfig(name="bad", type="invalid_type")
        result = await MCPClientManager.prepare_server_configs([cfg])
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_multiple_configs(self) -> None:
        cfg1 = FakeMCPServerConfig(name="good", type="sse", url="https://example.com/sse")
        cfg2 = FakeMCPServerConfig(name="bad", type="invalid_type")
        result = await MCPClientManager.prepare_server_configs([cfg1, cfg2])
        assert "good" in result
        assert "bad" not in result


class TestGetHeaders:
    """get_headers: merge static + injected auth headers."""

    def test_stdio_returns_empty(self) -> None:
        cfg = FakeMCPServerConfig(type="stdio", headers={"X-Test": "val"})
        assert MCPClientManager.get_headers(cfg) == {}

    def test_sse_returns_config_headers(self) -> None:
        cfg = FakeMCPServerConfig(
            type="sse",
            headers={"Authorization": "Bearer tok", "X-Custom": "val"},
        )
        headers = MCPClientManager.get_headers(cfg)
        assert headers == {"Authorization": "Bearer tok", "X-Custom": "val"}

    def test_no_headers_returns_empty(self) -> None:
        cfg = FakeMCPServerConfig(type="sse")
        assert MCPClientManager.get_headers(cfg) == {}


class TestResolveTlsPath:
    """_resolve_tls_path: ~ expansion, file/dir validation, actionable errors."""

    def test_file_returns_expanded_path(self, tls_certs: dict[str, str]) -> None:
        assert MCPClientManager._resolve_tls_path(tls_certs["cert"], "client_cert", "s") == tls_certs["cert"]

    def test_tilde_expansion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        pem = tmp_path / "client.pem"
        pem.write_text("dummy")
        assert MCPClientManager._resolve_tls_path("~/client.pem", "client_cert", "s") == str(pem)

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match=r"client_cert file not found"):
            MCPClientManager._resolve_tls_path("/nope/x.pem", "client_cert", "s")

    def test_directory_rejected_without_allow_dir(self, tls_certs: dict[str, str]) -> None:
        with pytest.raises(FileNotFoundError, match=r"client_cert file not found"):
            MCPClientManager._resolve_tls_path(tls_certs["ca_dir"], "client_cert", "s")

    def test_directory_accepted_with_allow_dir(self, tls_certs: dict[str, str]) -> None:
        assert (
            MCPClientManager._resolve_tls_path(tls_certs["ca_dir"], "ssl_verify", "s", allow_dir=True)
            == tls_certs["ca_dir"]
        )

    def test_missing_with_allow_dir_raises_file_or_directory(self) -> None:
        with pytest.raises(FileNotFoundError, match=r"file or directory not found"):
            MCPClientManager._resolve_tls_path("/nope/cadir", "ssl_verify", "s", allow_dir=True)


class TestBuildSSLContext:
    """_build_ssl_context: TLS/mTLS context construction, validation, and actionable errors."""

    def test_no_tls_returns_none(self) -> None:
        assert MCPClientManager._build_ssl_context(FakeMCPServerConfig()) is None

    def test_ssl_verify_false_disables_verification(self) -> None:
        ctx = MCPClientManager._build_ssl_context(FakeMCPServerConfig(ssl_verify=False))
        assert ctx is not None
        assert ctx.verify_mode == ssl.CERT_NONE
        assert ctx.check_hostname is False

    def test_ssl_verify_true_keeps_verification(self) -> None:
        ctx = MCPClientManager._build_ssl_context(FakeMCPServerConfig(ssl_verify=True))
        assert ctx is not None
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_ssl_verify_custom_ca_bundle(self, tls_certs: dict[str, str]) -> None:
        ctx = MCPClientManager._build_ssl_context(FakeMCPServerConfig(ssl_verify=tls_certs["ca"]))
        assert ctx is not None
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_ssl_verify_ca_directory_capath(self, tls_certs: dict[str, str]) -> None:
        """A CA bundle directory (OpenSSL capath) is accepted, not just a PEM file."""
        ctx = MCPClientManager._build_ssl_context(FakeMCPServerConfig(ssl_verify=tls_certs["ca_dir"]))
        assert ctx is not None
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_ssl_verify_ca_bundle_missing_raises(self) -> None:
        cfg = FakeMCPServerConfig(ssl_verify="/nonexistent/ca-bundle.pem")
        with pytest.raises(FileNotFoundError, match="ssl_verify"):
            MCPClientManager._build_ssl_context(cfg)

    def test_client_cert_with_separate_key(self, tls_certs: dict[str, str]) -> None:
        cfg = FakeMCPServerConfig(client_cert=tls_certs["cert"], client_key=tls_certs["key"])
        assert MCPClientManager._build_ssl_context(cfg) is not None

    def test_client_cert_with_bundled_key(self, tls_certs: dict[str, str]) -> None:
        cfg = FakeMCPServerConfig(client_cert=tls_certs["bundle"])
        assert MCPClientManager._build_ssl_context(cfg) is not None

    def test_ca_directory_with_client_cert_combo(self, tls_certs: dict[str, str]) -> None:
        """capath CA directory + mTLS client cert/key together (enterprise private-CA mTLS)."""
        cfg = FakeMCPServerConfig(
            ssl_verify=tls_certs["ca_dir"],
            client_cert=tls_certs["cert"],
            client_key=tls_certs["key"],
        )
        ctx = MCPClientManager._build_ssl_context(cfg)
        assert ctx is not None
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_encrypted_key_with_correct_passphrase(self, tls_certs: dict[str, str]) -> None:
        cfg = FakeMCPServerConfig(
            client_cert=tls_certs["cert"],
            client_key=tls_certs["enc_key"],
            client_key_password=tls_certs["passphrase"],
        )
        assert MCPClientManager._build_ssl_context(cfg) is not None

    def test_encrypted_key_wrong_passphrase_raises(self, tls_certs: dict[str, str]) -> None:
        cfg = FakeMCPServerConfig(
            client_cert=tls_certs["cert"],
            client_key=tls_certs["enc_key"],
            client_key_password="wrong-pass",
        )
        with pytest.raises(ValueError, match="passphrase"):
            MCPClientManager._build_ssl_context(cfg)

    def test_encrypted_key_missing_passphrase_raises(self, tls_certs: dict[str, str]) -> None:
        cfg = FakeMCPServerConfig(client_cert=tls_certs["cert"], client_key=tls_certs["enc_key"])
        with pytest.raises(ValueError, match="passphrase-protected"):
            MCPClientManager._build_ssl_context(cfg)

    def test_key_without_cert_raises(self, tls_certs: dict[str, str]) -> None:
        cfg = FakeMCPServerConfig(client_key=tls_certs["key"])
        with pytest.raises(ValueError, match=r"client_key.*without.*client_cert"):
            MCPClientManager._build_ssl_context(cfg)

    def test_password_without_cert_raises(self) -> None:
        cfg = FakeMCPServerConfig(client_key_password="secret")
        with pytest.raises(ValueError, match=r"client_key_password.*without.*client_cert"):
            MCPClientManager._build_ssl_context(cfg)

    def test_cert_not_found_raises(self) -> None:
        cfg = FakeMCPServerConfig(client_cert="/nonexistent/client.crt")
        with pytest.raises(FileNotFoundError, match="client_cert"):
            MCPClientManager._build_ssl_context(cfg)


class TestTLSClientFactory:
    """_build_tls_client_factory: TLS injection."""

    def test_factory_none_without_tls(self) -> None:
        assert MCPClientManager._build_tls_client_factory(FakeMCPServerConfig()) is None

    def test_factory_created_for_sse_with_tls(self, tls_certs: dict[str, str]) -> None:
        cfg = FakeMCPServerConfig(type="sse", url="https://x/sse", ssl_verify=tls_certs["ca"])
        factory = MCPClientManager._build_tls_client_factory(cfg)
        assert factory is not None

    def test_factory_none_without_tls_sse(self) -> None:
        cfg = FakeMCPServerConfig(type="sse", url="https://x/sse")
        assert MCPClientManager._build_tls_client_factory(cfg) is None

    @pytest.mark.asyncio
    async def test_factory_builds_async_client(self, tls_certs: dict[str, str]) -> None:
        import httpx2

        cfg = FakeMCPServerConfig(client_cert=tls_certs["cert"], client_key=tls_certs["key"])
        factory = MCPClientManager._build_tls_client_factory(cfg)
        assert factory is not None
        client = factory(headers={"X-Test": "1"}, timeout=None, auth=None)
        try:
            assert isinstance(client, httpx2.AsyncClient)
        finally:
            await client.aclose()


class TestHeadersMerging:
    """Verify that MCPConfig.headers are correctly returned by get_headers."""

    def test_headers_for_sse(self) -> None:
        cfg = FakeMCPServerConfig(
            type="sse",
            url="https://example.com/sse",
            headers={"Authorization": "Bearer {{secret:TOKEN}}", "X-Custom": "val"},
        )
        headers = MCPClientManager.get_headers(cfg)
        assert headers == {
            "Authorization": "Bearer {{secret:TOKEN}}",
            "X-Custom": "val",
        }

    def test_headers_for_streamable_http(self) -> None:
        cfg = FakeMCPServerConfig(
            type="streamable_http",
            url="https://example.com/mcp",
            headers={"X-API-Key": "my-key"},
        )
        headers = MCPClientManager.get_headers(cfg)
        assert headers == {"X-API-Key": "my-key"}

    def test_no_headers_for_stdio(self) -> None:
        cfg = FakeMCPServerConfig(
            type="stdio",
            command="mcp-server",
            url=None,
            headers={"Authorization": "Bearer tok"},
        )
        headers = MCPClientManager.get_headers(cfg)
        assert headers == {}

    def test_empty_headers(self) -> None:
        cfg = FakeMCPServerConfig(type="sse", url="https://example.com/sse")
        headers = MCPClientManager.get_headers(cfg)
        assert headers == {}


class TestRedirectGuardIntegration:
    """Verify build_streamable_http_client and _build_tls_client_factory inject redirect guards."""

    @pytest.mark.asyncio
    async def test_build_streamable_http_client_with_url(self) -> None:
        import httpx2

        client = MCPClientManager.build_streamable_http_client(
            headers={"Authorization": "Bearer tok"},
            url="https://api.example.com/mcp",
        )
        try:
            assert isinstance(client, httpx2.AsyncClient)
            assert client.follow_redirects is True
            assert "request" in client.event_hooks
            assert len(client.event_hooks["request"]) > 0
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_tls_factory_injects_redirect_guard(self, tls_certs: dict[str, str]) -> None:
        import httpx2

        cfg = FakeMCPServerConfig(
            name="custom-tls",
            url="https://api.example.com/sse",
            client_cert=tls_certs["cert"],
            client_key=tls_certs["key"],
        )
        factory = MCPClientManager._build_tls_client_factory(cfg)
        assert factory is not None
        client = factory(headers={"X-Secret": "123"}, timeout=None, auth=None)
        try:
            assert isinstance(client, httpx2.AsyncClient)
            assert client.follow_redirects is True
            assert "request" in client.event_hooks
            assert len(client.event_hooks["request"]) > 0
        finally:
            await client.aclose()

