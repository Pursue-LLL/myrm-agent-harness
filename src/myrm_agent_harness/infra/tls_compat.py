"""Enterprise TLS compatibility for Python 3.13+ / OpenSSL 3.x environments.

Python 3.13 enables ``VERIFY_X509_STRICT`` by default, which enforces
RFC 5280 §4.2.1.9 — a CA cert's ``basicConstraints`` MUST be marked critical.
Corporate TLS-inspection roots (Zscaler, Netskope, Palo Alto Prisma, etc.)
commonly set ``CA:TRUE`` *without* the critical bit, causing chain rejection
with ``BasicConstraints of CA cert not marked critical``.

This module provides a narrow relaxation: clearing *only* ``VERIFY_X509_STRICT``
while preserving certificate chain validation, hostname verification, and
expiry checks — strictly narrower than ``verify=False``.

Activation:
    Set ``MYRM_TLS_STRICT=0`` (or ``false``/``no``/``off``) to enable
    enterprise-compatible mode. Default (unset) keeps strict verification.

[INPUT]
- ssl (POS: Python standard library SSL module)
- os (POS: environment variable access)

[OUTPUT]
- tls_strict_disabled(): check if strict mode is opted out
- build_httpx_verify(): SSLContext or True for httpx/LiteLLM verify param
- apply_global_tls_relaxation(): urllib3 monkeypatch for 3rd-party libs

[POS]
Infrastructure TLS compatibility. Enables enterprise deployments behind
TLS-inspection proxies without disabling certificate verification entirely.
"""

from __future__ import annotations

import logging
import os
import ssl
from typing import Any, cast

logger = logging.getLogger(__name__)

_TLS_STRICT_ENV = "MYRM_TLS_STRICT"

_REPLACEMENT_CA_VARS = (
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
)

_TLS_STRICT_OFF_VALUES = frozenset({"0", "false", "no", "off"})


def tls_strict_disabled() -> bool:
    """True when ``MYRM_TLS_STRICT`` opts out of OpenSSL strict mode.

    Default (unset / any other value) is strict, matching Python 3.13's own
    default. Only the explicit off-values flip it.
    """
    return os.environ.get(_TLS_STRICT_ENV, "").strip().lower() in _TLS_STRICT_OFF_VALUES


def _clear_x509_strict(ctx: ssl.SSLContext, *, reason: str) -> ssl.SSLContext:
    """Clear only ``VERIFY_X509_STRICT`` from a context.

    Keeps certificate verification, hostname verification, expiry checks, and
    chain validation enabled — far narrower than disabling verify.
    """
    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict_flag and ctx.verify_flags & strict_flag:
        ctx.verify_flags &= ~strict_flag
        logger.info("event=tls_x509_strict_disabled reason=%s", reason)
    return ctx


def _replacement_ca_context(path: str) -> ssl.SSLContext:
    """Build a replacement trust-store context from a CA bundle path."""
    ctx = ssl.create_default_context(cafile=path)
    ctx.set_alpn_protocols(["h2", "http/1.1"])
    return _clear_x509_strict(ctx, reason=f"custom_ca:{path}")


def _additive_ca_context(path: str) -> ssl.SSLContext:
    """Build an additive trust-store context (default roots + extra bundle)."""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=path)
    ctx.set_alpn_protocols(["h2", "http/1.1"])
    return _clear_x509_strict(ctx, reason=f"additive_ca:{path}")


def _find_ca_bundle() -> ssl.SSLContext | None:
    """Resolve CA bundle from environment variables.

    Priority:
    1. SSL_CERT_FILE / REQUESTS_CA_BUNDLE — replacement semantics
    2. NODE_EXTRA_CA_CERTS — additive semantics (system roots + extra)

    Returns None when no env var is set (caller uses default verification).
    """
    for var in _REPLACEMENT_CA_VARS:
        path = os.environ.get(var, "").strip()
        if path and os.path.isfile(path):
            logger.info("event=tls_ca_bundle_loaded var=%s path=%s semantics=replacement", var, path)
            return _replacement_ca_context(path)

    node_extra = os.environ.get("NODE_EXTRA_CA_CERTS", "").strip()
    if node_extra and os.path.isfile(node_extra):
        logger.info("event=tls_ca_bundle_loaded var=NODE_EXTRA_CA_CERTS path=%s semantics=additive", node_extra)
        return _additive_ca_context(node_extra)

    return None


def _default_strict_relaxed_context() -> ssl.SSLContext:
    """Build a default trust-store context with VERIFY_X509_STRICT cleared."""
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["h2", "http/1.1"])
    return _clear_x509_strict(ctx, reason="env_toggle")


def build_httpx_verify() -> ssl.SSLContext | bool:
    """Return the value for httpx/LiteLLM ``verify=`` / ``ssl_verify=`` parameter.

    Resolution order:
    1. Custom CA bundle env var → context trusting that bundle, strict relaxed.
    2. No bundle but ``MYRM_TLS_STRICT=0`` → default store with strict cleared.
    3. Otherwise → ``True`` (default strict verification).
    """
    ca_ctx = _find_ca_bundle()
    if ca_ctx is not None:
        return ca_ctx
    if tls_strict_disabled():
        return _default_strict_relaxed_context()
    return True


def apply_global_tls_relaxation() -> bool:
    """Strip ``VERIFY_X509_STRICT`` from urllib3's context builder when opted in.

    Covers the ``requests``/``huggingface_hub``/``urllib3`` dependency chain
    that bypasses our httpx/LiteLLM context. The patch is idempotent (guarded
    by a sentinel attribute) and a no-op when urllib3 isn't importable.

    Call at application startup before any HTTP client is created.

    Returns True if patch was applied (or already in place), False otherwise.
    """
    if not tls_strict_disabled():
        return False

    strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if not strict_flag:
        return False

    try:
        import urllib3.util.ssl_ as _u3ssl
    except Exception:
        logger.debug("event=tls_urllib3_patch_skipped reason=import_failed")
        return False

    if getattr(_u3ssl.create_urllib3_context, "_myrm_strict_relaxed", False):
        return True

    _orig = _u3ssl.create_urllib3_context

    def _relaxed_create_urllib3_context(*args: Any, **kwargs: Any) -> ssl.SSLContext:
        ctx = cast(ssl.SSLContext, _orig(*args, **kwargs))
        if tls_strict_disabled() and ctx.verify_flags & strict_flag:
            ctx.verify_flags &= ~strict_flag
        return ctx

    _relaxed_create_urllib3_context._myrm_strict_relaxed = True  # type: ignore[attr-defined]
    _u3ssl.create_urllib3_context = _relaxed_create_urllib3_context  # type: ignore[assignment]
    logger.info("event=tls_x509_strict_disabled reason=urllib3_global_patch")
    return True


_TLS_ERROR_PATTERNS = (
    "basic constraints",
    "basicconstraints",
    "not marked critical",
    "certificate verify failed",
    "ssl: certificate_verify_failed",
    "unable to get local issuer",
    "[ssl: certificate_verify_failed]",
    "self-signed certificate in certificate chain",
)


def is_tls_strict_error(error_message: str) -> bool:
    """Detect if an error message indicates a TLS strict-mode rejection.

    Used by error handlers to attach actionable remediation hints.
    """
    lower = error_message.lower()
    return any(pattern in lower for pattern in _TLS_ERROR_PATTERNS)


def get_tls_remediation_hint() -> str:
    """Return user-facing hint when a TLS strict error is detected."""
    if tls_strict_disabled():
        return (
            "TLS enterprise mode is enabled but the connection still failed. "
            "Check that your CA bundle path (SSL_CERT_FILE) is correct."
        )
    return (
        "This may be caused by enterprise TLS inspection (Zscaler, Netskope, etc.). "
        "Set environment variable MYRM_TLS_STRICT=0 or enable "
        "'Enterprise Network Compatibility' in Settings → Advanced."
    )
