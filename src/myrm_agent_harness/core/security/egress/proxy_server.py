# INPUT: Inbound HTTP/HTTPS client sockets from sandbox, target remote endpoints, SentinelManager
# OUTPUT: Outbound network traffic with sentinel vouchers substituted by real secrets, ephemeral CA management
# POS: Harness core security egress layer. Asyncio-based loopback egress proxy for transparent secret substitution.

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import os
import ssl
import tempfile
from typing import TYPE_CHECKING

from .sentinel import SentinelManager, StreamingSentinelScanner, get_global_sentinel_manager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EphemeralCaManager:
    """Generates and manages in-memory self-signed CA and dynamic leaf certificates for TLS interception.

    All certificates are ephemeral and created with 0600 permissions in memory or temp storage.
    Files are strictly unlinked upon proxy termination to prevent credential leakage.
    """

    def __init__(self) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        self._ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Myrm Ephemeral Sandbox CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Myrm Harness Security"),
        ])
        now = datetime.datetime.now(datetime.UTC)
        self._ca_cert = (
            x509.CertificateBuilder()
            .subject_name(self._name)
            .issuer_name(self._name)
            .public_key(self._ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=7))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(self._ca_key, hashes.SHA256())
        )

        from cryptography.hazmat.primitives import serialization

        self._ca_cert_pem = self._ca_cert.public_bytes(serialization.Encoding.PEM)
        self._ca_key_pem = self._ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self._cert_cache: dict[str, ssl.SSLContext] = {}
        self._temp_ca_path: str | None = None

    @property
    def ca_bundle_path(self) -> str:
        """Get or create temporary CA certificate bundle path for environment injection."""
        if self._temp_ca_path is None or not os.path.exists(self._temp_ca_path):
            fd, path = tempfile.mkstemp(prefix="myrm_ca_", suffix=".crt")
            with os.fdopen(fd, "wb") as f:
                f.write(self._ca_cert_pem)
            with contextlib.suppress(OSError):
                os.chmod(path, 0o600)
            self._temp_ca_path = path
        return self._temp_ca_path

    def get_server_ssl_context(self, hostname: str) -> ssl.SSLContext:
        """Create or fetch cached SSLContext signed by our ephemeral CA for a given hostname."""
        if hostname in self._cert_cache:
            return self._cert_cache[hostname]

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
        now = datetime.datetime.now(datetime.UTC)

        # Subject alternative names
        san = x509.SubjectAlternativeName([x509.DNSName(hostname)])

        leaf_cert = (
            x509.CertificateBuilder()
            .subject_name(leaf_name)
            .issuer_name(self._name)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=7))
            .add_extension(san, critical=False)
            .sign(self._ca_key, hashes.SHA256())
        )

        leaf_cert_pem = leaf_cert.public_bytes(serialization.Encoding.PEM)
        leaf_key_pem = leaf_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        # Build in-memory SSLContext
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        with tempfile.NamedTemporaryFile("wb", delete=False) as cert_f, tempfile.NamedTemporaryFile("wb", delete=False) as key_f:
            cert_f.write(leaf_cert_pem)
            key_f.write(leaf_key_pem)
            cert_path, key_path = cert_f.name, key_f.name

        try:
            ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        finally:
            for p in (cert_path, key_path):
                if os.path.exists(p):
                    with contextlib.suppress(OSError):
                        os.unlink(p)

        self._cert_cache[hostname] = ctx
        return ctx

    def cleanup(self) -> None:
        """Remove temporary CA bundle file from disk."""
        if self._temp_ca_path and os.path.exists(self._temp_ca_path):
            with contextlib.suppress(OSError):
                os.unlink(self._temp_ca_path)
            self._temp_ca_path = None
        self._cert_cache.clear()


class LoopbackEgressProxy:
    """Async loopback egress proxy intercepting outbound traffic to transparently substitute sentinel vouchers.

    Bound to 127.0.0.1 on an ephemeral port. Inspects outbound requests and injects real secrets.
    """

    def __init__(
        self,
        sentinel_manager: SentinelManager | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        enable_tls_interception: bool = True,
    ) -> None:
        self._manager: SentinelManager = sentinel_manager or get_global_sentinel_manager()
        self._host: str = host
        self._requested_port: int = port
        self._enable_tls: bool = enable_tls_interception
        self._server: asyncio.Server | None = None
        self._assigned_port: int = 0
        self._ca_manager: EphemeralCaManager | None = EphemeralCaManager() if enable_tls_interception else None
        self._running: bool = False

    @property
    def port(self) -> int:
        """Get the assigned port of the running proxy."""
        return self._assigned_port

    @property
    def proxy_url(self) -> str:
        """Get the HTTP proxy connection URL."""
        if not self._assigned_port:
            raise RuntimeError("LoopbackEgressProxy is not running")
        return f"http://{self._host}:{self._assigned_port}"

    @property
    def ca_bundle_path(self) -> str | None:
        """Get path to the ephemeral CA bundle for environment variable injection."""
        return self._ca_manager.ca_bundle_path if self._ca_manager else None

    def get_env_overrides(self) -> dict[str, str]:
        """Generate process environment variable overrides for child process redirection."""
        url = self.proxy_url
        env: dict[str, str] = {
            "http_proxy": url,
            "https_proxy": url,
            "HTTP_PROXY": url,
            "HTTPS_PROXY": url,
            "ALL_PROXY": url,
            "NO_PROXY": "localhost,127.0.0.1,::1",
            "no_proxy": "localhost,127.0.0.1,::1",
        }
        ca = self.ca_bundle_path
        if ca:
            env["REQUESTS_CA_BUNDLE"] = ca
            env["SSL_CERT_FILE"] = ca
            env["NODE_EXTRA_CA_CERTS"] = ca
            env["CURL_CA_BUNDLE"] = ca
        return env

    async def start(self) -> str:
        """Start the loopback proxy server.

        Returns:
            The proxy URL (e.g. 'http://127.0.0.1:54321').
        """
        if self._server is not None:
            return self.proxy_url

        self._server = await asyncio.start_server(
            self._handle_client,
            host=self._host,
            port=self._requested_port,
        )
        sockets = self._server.sockets
        if not sockets:
            raise RuntimeError("Failed to bind loopback proxy socket")
        self._assigned_port = sockets[0].getsockname()[1]
        self._running = True
        logger.info("[EGRESS_PROXY] Loopback egress proxy listening on %s", self.proxy_url)
        return self.proxy_url

    async def stop(self) -> None:
        """Stop the loopback proxy server and clean up ephemeral artifacts."""
        self._running = False
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if self._ca_manager is not None:
            self._ca_manager.cleanup()

        logger.info("[EGRESS_PROXY] Loopback egress proxy stopped")

    async def __aenter__(self) -> LoopbackEgressProxy:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.stop()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a new incoming proxy client connection."""
        try:
            line_bytes = await reader.readline()
            if not line_bytes:
                writer.close()
                await writer.wait_closed()
                return

            req_line = line_bytes.decode("latin1", errors="replace").strip()
            parts = req_line.split()
            if len(parts) < 2:
                writer.close()
                await writer.wait_closed()
                return

            method, target = parts[0].upper(), parts[1]

            if method == "CONNECT":
                await self._handle_connect(target, reader, writer)
            else:
                await self._handle_http_forward(method, target, line_bytes, reader, writer)
        except Exception as e:
            logger.debug("[EGRESS_PROXY] Error in client handler: %s", e)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_connect(
        self,
        target: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle HTTP CONNECT tunneling with optional TLS interception."""
        host_port = target.split(":")
        target_host = host_port[0]
        target_port = int(host_port[1]) if len(host_port) > 1 else 443

        # Acknowledge CONNECT establishment
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()

        # Connect to remote target
        try:
            remote_reader, remote_writer = await asyncio.open_connection(target_host, target_port)
        except Exception as e:
            logger.warning("[EGRESS_PROXY] Failed to connect to remote target %s:%d: %s", target_host, target_port, e)
            writer.close()
            await writer.wait_closed()
            return

        # Blind TCP tunnel with stream-level substitution
        await self._pipe_bidirectional(reader, writer, remote_reader, remote_writer)

    async def _handle_http_forward(
        self,
        method: str,
        target: str,
        first_line_bytes: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle standard HTTP forwarding with full header & body substitution."""
        # Read headers until empty line
        raw_headers: list[bytes] = []
        content_length = 0
        while True:
            h_line = await reader.readline()
            if not h_line or h_line in (b"\r\n", b"\n"):
                break
            raw_headers.append(h_line)
            h_str = h_line.decode("latin1", errors="replace").lower()
            if h_str.startswith("content-length:"):
                try:
                    content_length = int(h_str.split(":", 1)[1].strip())
                except ValueError:
                    content_length = 0

        # Parse target host from URL or Host header
        host = ""
        port = 80
        if target.startswith("http://"):
            from urllib.parse import urlparse

            parsed = urlparse(target)
            host = parsed.hostname or ""
            port = parsed.port or 80
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
        else:
            path = target
            for h in raw_headers:
                h_str = h.decode("latin1", errors="replace")
                if h_str.lower().startswith("host:"):
                    host_val = h_str.split(":", 1)[1].strip()
                    h_parts = host_val.split(":")
                    host = h_parts[0]
                    port = int(h_parts[1]) if len(h_parts) > 1 else 80
                    break

        if not host:
            writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\nNo Host specified")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        # Connect to remote HTTP target
        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)
        except Exception as e:
            logger.warning("[EGRESS_PROXY] Failed to connect to %s:%d: %s", host, port, e)
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\nFailed to connect to upstream server")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        # Substitute request line (query parameters) and headers
        substituted_path = self._manager.substitute_text(path)
        outbound_first_line = f"{method} {substituted_path} HTTP/1.1\r\n".encode("latin1")
        remote_writer.write(outbound_first_line)

        for h in raw_headers:
            h_str = h.decode("latin1", errors="replace")
            # Don't forward proxy-specific headers
            if h_str.lower().startswith("proxy-"):
                continue
            sub_h = self._manager.substitute_text(h_str)
            remote_writer.write(sub_h.encode("latin1"))

        remote_writer.write(b"\r\n")
        await remote_writer.drain()

        # Stream body with sliding-window substitution
        if content_length > 0:
            scanner = StreamingSentinelScanner(self._manager)
            bytes_left = content_length
            while bytes_left > 0:
                chunk = await reader.read(min(bytes_left, 16384))
                if not chunk:
                    break
                bytes_left -= len(chunk)
                ready_chunk = scanner.feed(chunk)
                if ready_chunk:
                    remote_writer.write(ready_chunk)
                    await remote_writer.drain()
            remaining = scanner.flush()
            if remaining:
                remote_writer.write(remaining)
                await remote_writer.drain()

        # Pipe remote response back to client verbatim
        try:
            while True:
                resp_chunk = await remote_reader.read(16384)
                if not resp_chunk:
                    break
                writer.write(resp_chunk)
                await writer.drain()
        except Exception:
            pass
        finally:
            remote_writer.close()
            await remote_writer.wait_closed()
            writer.close()
            await writer.wait_closed()

    async def _pipe_bidirectional(
        self,
        c_reader: asyncio.StreamReader,
        c_writer: asyncio.StreamWriter,
        r_reader: asyncio.StreamReader,
        r_writer: asyncio.StreamWriter,
    ) -> None:
        """Pipe bidirectional TCP data with egress scanner substitution on client-to-remote path."""
        scanner = StreamingSentinelScanner(self._manager)

        async def _client_to_remote() -> None:
            try:
                while True:
                    data = await c_reader.read(16384)
                    if not data:
                        break
                    # Substitute any sentinels streaming outbound
                    replaced = scanner.feed(data)
                    if replaced:
                        r_writer.write(replaced)
                        await r_writer.drain()
                flush_rem = scanner.flush()
                if flush_rem:
                    r_writer.write(flush_rem)
                    await r_writer.drain()
            except Exception:
                pass
            finally:
                try:
                    r_writer.close()
                    await r_writer.wait_closed()
                except Exception:
                    pass

        async def _remote_to_client() -> None:
            try:
                while True:
                    data = await r_reader.read(16384)
                    if not data:
                        break
                    c_writer.write(data)
                    await c_writer.drain()
            except Exception:
                pass
            finally:
                try:
                    c_writer.close()
                    await c_writer.wait_closed()
                except Exception:
                    pass

        await asyncio.gather(_client_to_remote(), _remote_to_client(), return_exceptions=True)
