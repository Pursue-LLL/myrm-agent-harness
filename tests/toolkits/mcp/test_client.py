"""Tests for MCP client management (config conversion, auth injection, initialization, TLS/mTLS)."""

from __future__ import annotations

import datetime
import ssl
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestConvertServerConfig:
    """convert_server_config_to_client_format: transport config conversion."""

    def test_sse_config(self) -> None:
        cfg = FakeMCPServerConfig(type="sse", url="https://api.example.com/sse")
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["transport"] == "sse"
        assert result["url"] == "https://api.example.com/sse"
        assert result["timeout"] == 15.0
        assert result["sse_read_timeout"] == 120.0
        assert "session_kwargs" in result
        sk = result["session_kwargs"]
        assert isinstance(sk, dict)
        assert sk["read_timeout_seconds"] == timedelta(seconds=120.0)

    def test_streamable_http_config(self) -> None:
        cfg = FakeMCPServerConfig(type="streamable_http", url="https://api.example.com/http")
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["transport"] == "streamable_http"
        assert result["url"] == "https://api.example.com/http"

    def test_stdio_config(self) -> None:
        cfg = FakeMCPServerConfig(
            type="stdio",
            url=None,
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
        )
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["transport"] == "stdio"
        assert result["command"] == "npx"
        assert result["args"] == ["-y", "@modelcontextprotocol/server-filesystem"]

    def test_stdio_no_args(self) -> None:
        cfg = FakeMCPServerConfig(type="stdio", url=None, command="mcp-server", args=None)
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["args"] == []

    def test_unsupported_type_raises(self) -> None:
        cfg = FakeMCPServerConfig(type="websocket")
        with pytest.raises(ValueError, match="Unsupported transport type"):
            MCPClientManager.convert_server_config_to_client_format(cfg)

    def test_extra_params_merged(self) -> None:
        cfg = FakeMCPServerConfig(extra_params={"headers": {"X-Custom": "val"}})
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["headers"] == {"X-Custom": "val"}

    def test_custom_timeouts(self) -> None:
        cfg = FakeMCPServerConfig(connect_timeout=30.0, execute_timeout=300.0)
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["timeout"] == 30.0
        assert result["sse_read_timeout"] == 300.0


class TestInjectAuthHeaders:
    """_inject_auth_headers: OAuth/auth header injection for HTTP transports."""

    @pytest.mark.asyncio
    async def test_no_auth_provider(self) -> None:
        cfg = FakeMCPServerConfig(auth_provider=None)
        client_config: dict[str, object] = {"transport": "sse"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert "headers" not in client_config

    @pytest.mark.asyncio
    async def test_stdio_skips_auth(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer token"})
        cfg = FakeMCPServerConfig(type="stdio", auth_provider=provider)
        client_config: dict[str, object] = {"transport": "stdio"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        provider.get_auth_headers.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sse_injects_headers(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer abc123"})
        cfg = FakeMCPServerConfig(auth_provider=provider)
        client_config: dict[str, object] = {"transport": "sse"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert client_config["headers"] == {"Authorization": "Bearer abc123"}

    @pytest.mark.asyncio
    async def test_streamable_http_injects_headers(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={"X-Api-Key": "key123"})
        cfg = FakeMCPServerConfig(type="streamable_http", auth_provider=provider)
        client_config: dict[str, object] = {"transport": "streamable_http"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert client_config["headers"] == {"X-Api-Key": "key123"}

    @pytest.mark.asyncio
    async def test_merges_with_existing_headers(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer new"})
        cfg = FakeMCPServerConfig(auth_provider=provider)
        client_config: dict[str, object] = {
            "transport": "sse",
            "headers": {"X-Existing": "keep"},
        }
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        headers = client_config["headers"]
        assert headers == {"X-Existing": "keep", "Authorization": "Bearer new"}

    @pytest.mark.asyncio
    async def test_empty_auth_headers_skips(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(return_value={})
        cfg = FakeMCPServerConfig(auth_provider=provider)
        client_config: dict[str, object] = {"transport": "sse"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert "headers" not in client_config

    @pytest.mark.asyncio
    async def test_auth_failure_is_non_fatal(self) -> None:
        provider = MagicMock()
        provider.get_auth_headers = AsyncMock(side_effect=RuntimeError("Token expired"))
        cfg = FakeMCPServerConfig(auth_provider=provider)
        client_config: dict[str, object] = {"transport": "sse"}
        await MCPClientManager._inject_auth_headers(cfg, client_config)
        assert "headers" not in client_config


class TestInitializeClient:
    """initialize_client: multi-server client initialization."""

    @pytest.mark.asyncio
    async def test_empty_config(self) -> None:
        client = await MCPClientManager.initialize_client(None)
        assert client is not None

    @pytest.mark.asyncio
    async def test_empty_list(self) -> None:
        client = await MCPClientManager.initialize_client([])
        assert client is not None

    @pytest.mark.asyncio
    async def test_valid_config_creates_client(self) -> None:
        cfg = FakeMCPServerConfig(name="my-sse", type="sse", url="https://example.com/sse")
        with patch(
            "myrm_agent_harness.toolkits.mcp.client.MultiServerMCPClient",
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            client = await MCPClientManager.initialize_client([cfg])
            assert client is not None
            mock_cls.assert_called_once()
            call_args = mock_cls.call_args[0][0]
            assert "my-sse" in call_args

    @pytest.mark.asyncio
    async def test_config_error_skips_server(self) -> None:
        cfg = FakeMCPServerConfig(name="bad", type="invalid_type")
        with patch(
            "myrm_agent_harness.toolkits.mcp.client.MultiServerMCPClient",
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            client = await MCPClientManager.initialize_client([cfg])
            assert client is not None

    @pytest.mark.asyncio
    async def test_client_init_failure_returns_empty(self) -> None:
        cfg = FakeMCPServerConfig(name="good", type="sse", url="https://example.com/sse")
        with patch(
            "myrm_agent_harness.toolkits.mcp.client.MultiServerMCPClient",
            side_effect=[RuntimeError("init failed"), MagicMock()],
        ):
            client = await MCPClientManager.initialize_client([cfg])
            assert client is not None


class TestResolveTlsPath:
    """_resolve_tls_path: ~ expansion, file/dir validation, actionable errors."""

    def test_file_returns_expanded_path(self, tls_certs: dict[str, str]) -> None:
        assert (
            MCPClientManager._resolve_tls_path(tls_certs["cert"], "client_cert", "s")
            == tls_certs["cert"]
        )

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
            MCPClientManager._resolve_tls_path(
                tls_certs["ca_dir"], "ssl_verify", "s", allow_dir=True
            )
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
        ctx = MCPClientManager._build_ssl_context(
            FakeMCPServerConfig(ssl_verify=tls_certs["ca_dir"])
        )
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
    """_build_tls_client_factory + convert_server_config_to_client_format TLS injection."""

    def test_factory_none_without_tls(self) -> None:
        assert MCPClientManager._build_tls_client_factory(FakeMCPServerConfig()) is None

    def test_factory_injected_for_sse_with_tls(self, tls_certs: dict[str, str]) -> None:
        cfg = FakeMCPServerConfig(type="sse", url="https://x/sse", ssl_verify=tls_certs["ca"])
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert "httpx_client_factory" in result

    def test_factory_not_injected_without_tls(self) -> None:
        cfg = FakeMCPServerConfig(type="sse", url="https://x/sse")
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert "httpx_client_factory" not in result

    def test_factory_not_injected_for_stdio(self, tls_certs: dict[str, str]) -> None:
        cfg = FakeMCPServerConfig(type="stdio", url=None, command="mcp", ssl_verify=tls_certs["ca"])
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert "httpx_client_factory" not in result

    @pytest.mark.asyncio
    async def test_factory_builds_async_client(self, tls_certs: dict[str, str]) -> None:
        import httpx

        cfg = FakeMCPServerConfig(client_cert=tls_certs["cert"], client_key=tls_certs["key"])
        factory = MCPClientManager._build_tls_client_factory(cfg)
        assert factory is not None
        client = factory(headers={"X-Test": "1"}, timeout=None, auth=None)
        try:
            assert isinstance(client, httpx.AsyncClient)
        finally:
            await client.aclose()


class TestHeadersMerging:
    """Verify that MCPConfig.headers are merged into SSE/streamable_http client_config."""

    def test_headers_merged_into_sse_config(self) -> None:
        cfg = FakeMCPServerConfig(
            type="sse",
            url="https://example.com/sse",
            headers={"Authorization": "Bearer {{secret:TOKEN}}", "X-Custom": "val"},
        )
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["headers"] == {
            "Authorization": "Bearer {{secret:TOKEN}}",
            "X-Custom": "val",
        }

    def test_headers_merged_into_streamable_http_config(self) -> None:
        cfg = FakeMCPServerConfig(
            type="streamable_http",
            url="https://example.com/mcp",
            headers={"X-API-Key": "my-key"},
        )
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["headers"] == {"X-API-Key": "my-key"}

    def test_headers_merged_with_extra_params_headers(self) -> None:
        cfg = FakeMCPServerConfig(
            type="sse",
            url="https://example.com/sse",
            headers={"Authorization": "Bearer tok"},
            extra_params={"headers": {"X-From-Extra": "yes"}},
        )
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["headers"]["Authorization"] == "Bearer tok"
        assert result["headers"]["X-From-Extra"] == "yes"

    def test_headers_override_extra_params_headers(self) -> None:
        """First-class headers field takes precedence over extra_params.headers."""
        cfg = FakeMCPServerConfig(
            type="sse",
            url="https://example.com/sse",
            headers={"Authorization": "Bearer new"},
            extra_params={"headers": {"Authorization": "Bearer old"}},
        )
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert result["headers"]["Authorization"] == "Bearer new"

    def test_no_headers_for_stdio(self) -> None:
        cfg = FakeMCPServerConfig(
            type="stdio",
            command="mcp-server",
            url=None,
            headers={"Authorization": "Bearer tok"},
        )
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert "headers" not in result

    def test_empty_headers_not_added(self) -> None:
        cfg = FakeMCPServerConfig(type="sse", url="https://example.com/sse")
        result = MCPClientManager.convert_server_config_to_client_format(cfg)
        assert "headers" not in result or result.get("headers") is None
