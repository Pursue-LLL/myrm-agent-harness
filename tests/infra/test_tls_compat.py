"""Unit tests for infra/tls_compat.py."""

from __future__ import annotations

import asyncio
import os
import ssl
from unittest.mock import patch

import pytest

from myrm_agent_harness.infra.tls_compat import (
    apply_global_tls_relaxation,
    build_httpx_verify,
    create_httpx_client,
    get_tls_remediation_hint,
    is_tls_strict_error,
    tls_strict_disabled,
)


class TestTlsStrictDisabled:
    """Tests for tls_strict_disabled() env var parsing."""

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "FALSE", "No", "OFF"])
    def test_disabled_values(self, value: str) -> None:
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": value}):
            assert tls_strict_disabled() is True

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "anything"])
    def test_enabled_values(self, value: str) -> None:
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": value}):
            assert tls_strict_disabled() is False

    def test_unset_defaults_to_strict(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MYRM_TLS_STRICT", None)
            assert tls_strict_disabled() is False

    def test_whitespace_trimmed(self) -> None:
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "  0  "}):
            assert tls_strict_disabled() is True


class TestBuildHttpxVerify:
    """Tests for build_httpx_verify() SSL context construction."""

    def test_default_returns_true(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MYRM_TLS_STRICT", None)
            os.environ.pop("SSL_CERT_FILE", None)
            os.environ.pop("REQUESTS_CA_BUNDLE", None)
            os.environ.pop("NODE_EXTRA_CA_CERTS", None)
            assert build_httpx_verify() is True

    def test_strict_disabled_returns_context(self) -> None:
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
            os.environ.pop("SSL_CERT_FILE", None)
            os.environ.pop("REQUESTS_CA_BUNDLE", None)
            os.environ.pop("NODE_EXTRA_CA_CERTS", None)
            result = build_httpx_verify()
            assert isinstance(result, ssl.SSLContext)
            assert result.check_hostname is True
            assert result.verify_mode == ssl.CERT_REQUIRED

    def test_strict_disabled_clears_x509_strict(self) -> None:
        strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if not strict_flag:
            pytest.skip("VERIFY_X509_STRICT not available (Python < 3.13)")
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
            os.environ.pop("SSL_CERT_FILE", None)
            result = build_httpx_verify()
            assert isinstance(result, ssl.SSLContext)
            assert not (result.verify_flags & strict_flag)

    def test_custom_ca_replacement(self, tmp_path: pytest.TempPathFactory) -> None:
        ca_file = tmp_path / "ca-bundle.crt"  # type: ignore[operator]
        ca_file.write_bytes(ssl.get_default_verify_paths().cafile and
                            open(ssl.get_default_verify_paths().cafile, "rb").read() or b"")
        if ca_file.stat().st_size == 0:
            pytest.skip("No system CA bundle available for test")
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0", "SSL_CERT_FILE": str(ca_file)}):
            result = build_httpx_verify()
            assert isinstance(result, ssl.SSLContext)

    def test_nonexistent_ca_path_falls_back(self) -> None:
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0", "SSL_CERT_FILE": "/nonexistent/ca.crt"}):
            result = build_httpx_verify()
            assert isinstance(result, ssl.SSLContext)

    def test_additive_ca_via_node_extra(self, tmp_path: pytest.TempPathFactory) -> None:
        ca_file = tmp_path / "extra-ca.crt"  # type: ignore[operator]
        ca_file.write_bytes(ssl.get_default_verify_paths().cafile and
                            open(ssl.get_default_verify_paths().cafile, "rb").read() or b"")
        if ca_file.stat().st_size == 0:
            pytest.skip("No system CA bundle available for test")
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0", "NODE_EXTRA_CA_CERTS": str(ca_file)}):
            os.environ.pop("SSL_CERT_FILE", None)
            os.environ.pop("REQUESTS_CA_BUNDLE", None)
            result = build_httpx_verify()
            assert isinstance(result, ssl.SSLContext)


class TestCreateHttpxClient:
    """Tests for create_httpx_client() factory function."""

    def test_default_mode_no_injection(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MYRM_TLS_STRICT", None)
            client = create_httpx_client(timeout=5.0)
            assert client is not None
            client.close()

    def test_enterprise_mode_injects_context(self) -> None:
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
            os.environ.pop("SSL_CERT_FILE", None)
            client = create_httpx_client(timeout=5.0)
            pool = getattr(client._transport, "_pool", None)
            if pool is not None:
                ctx = getattr(pool, "_ssl_context", None)
                assert isinstance(ctx, ssl.SSLContext)
                assert ctx.check_hostname is True
                assert ctx.verify_mode == ssl.CERT_REQUIRED
            client.close()

    def test_caller_verify_false_respected(self) -> None:
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
            client = create_httpx_client(timeout=5.0, verify=False)
            assert client is not None
            client.close()

    def test_caller_verify_true_respected(self) -> None:
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
            client = create_httpx_client(timeout=5.0, verify=True)
            assert client is not None
            client.close()

    def test_kwargs_passthrough(self) -> None:
        import httpx

        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
            client = create_httpx_client(
                timeout=httpx.Timeout(30.0, connect=5.0),
                follow_redirects=False,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
            assert client._timeout.connect == 5.0
            assert client._timeout.read == 30.0
            client.close()

    def test_context_manager_usage(self) -> None:
        import asyncio

        async def _run() -> None:
            with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
                async with create_httpx_client(timeout=5.0) as client:
                    assert client is not None

        asyncio.run(_run())


class TestApplyGlobalTlsRelaxation:
    """Tests for apply_global_tls_relaxation() urllib3 monkeypatch."""

    def test_noop_when_strict_enabled(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MYRM_TLS_STRICT", None)
            assert apply_global_tls_relaxation() is False

    def test_applies_when_strict_disabled(self) -> None:
        strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if not strict_flag:
            pytest.skip("VERIFY_X509_STRICT not available (Python < 3.13)")
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
            result = apply_global_tls_relaxation()
            assert result is True

    def test_idempotent(self) -> None:
        strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
        if not strict_flag:
            pytest.skip("VERIFY_X509_STRICT not available (Python < 3.13)")
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
            first = apply_global_tls_relaxation()
            second = apply_global_tls_relaxation()
            assert first is True
            assert second is True


class TestIsTlsStrictError:
    """Tests for is_tls_strict_error() pattern detection."""

    @pytest.mark.parametrize(
        "msg",
        [
            "BasicConstraints of CA cert not marked critical",
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
            "unable to get local issuer certificate",
            "self-signed certificate in certificate chain",
        ],
    )
    def test_detects_tls_errors(self, msg: str) -> None:
        assert is_tls_strict_error(msg) is True

    @pytest.mark.parametrize(
        "msg",
        [
            "Connection refused",
            "DNS resolution failed",
            "Timeout exceeded",
        ],
    )
    def test_ignores_non_tls_errors(self, msg: str) -> None:
        assert is_tls_strict_error(msg) is False


class TestGetTlsRemediationHint:
    """Tests for get_tls_remediation_hint() user-facing messages."""

    def test_hint_when_strict_enabled(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MYRM_TLS_STRICT", None)
            hint = get_tls_remediation_hint()
            assert "MYRM_TLS_STRICT=0" in hint
            assert "Enterprise Network Compatibility" in hint

    def test_hint_when_strict_disabled(self) -> None:
        with patch.dict(os.environ, {"MYRM_TLS_STRICT": "0"}):
            hint = get_tls_remediation_hint()
            assert "SSL_CERT_FILE" in hint
