"""Web和URL相关工具函数

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- urllib.parse::urlparse, urlunparse, unquote (POS: Python 标准库，URL 解析和编码)
- ipaddress (POS: Python 标准库，IP 地址/网络解析)
- socket (POS: Python 标准库，DNS 解析)
- httpx (POS: 异步 HTTP 客户端，用于 DNS pinning transport)

[OUTPUT]
- normalize_url(): URL 标准化（解码、小写、去 www、去尾斜杠），返回去重版和完整版
- extract_domain(): 提取域名（支持去除 www 前缀）
- is_valid_url(): 验证 URL 格式是否有效
- clean_search_url(): 清理搜索引擎 URL（去除追踪参数）
- create_dns_pin_map(): 基于 SSRFResult 构建 hostname→IP 映射（SSRFResult 来自 core.security.guards.ssrf）
- build_host_resolver_rules(): 构建 Chrome --host-resolver-rules 参数
- is_blocked_ip(): IP 黑名单检查（单一数据源，被 core.security.guards.ssrf 等共用）
- validate_scheme_and_hostname(): URL scheme 和 hostname 验证（含 parser-confusing 字符防御、hostname 尾部点规范化、hostname 后缀匹配）

[POS]
Web and URL utilities. Provides URL normalization, parsing, cleanup, and type determination functions.

"""

from __future__ import annotations

import ipaddress
import logging
import re as _re
from typing import Protocol
from urllib.parse import unquote, urlparse, urlunparse

logger = logging.getLogger(__name__)


# ============================================================================
# URL 标准化和清理
# ============================================================================


def normalize_url(url: str) -> tuple[str, str]:
    """URL标准化: 解码+小写+去www+去尾斜杠，返回带/不带fragment的两个版本。

    标准化步骤：
    1. URL解码：将 %XX 编码转换为实际字符（如中文），确保嵌入模型能识别语义相似度
    2. 小写化：scheme、netloc和path全部转小写（确保大小写不同的URL能被识别为相同）
    3. 去除www前缀
    4. 去除路径尾部斜杠
    5. 保留query参数
    6. 返回两个版本：不带fragment（用于去重）和带fragment（用于语义分析）

    Args:
        url: 要标准化的URL

    Returns:
        (不带fragment的URL, 带fragment的URL)
        - 第一个：用于去重，同一页面的不同锚点会被识别为相同
        - 第二个：用于语义分析和显示，保留完整的定位信息

    使用场景：
        - 去重：使用返回的第一个值（不带fragment）作为去重key
        - 语义分析/显示：使用返回的第二个值（带fragment），存入metadata

    示例：
        # 基本用法
        url_dedup, url_semantic = normalize_url("https://docs.langchain.com/agents#system-prompt")
        # url_dedup: "https://docs.langchain.com/agents"
        # url_semantic: "https://docs.langchain.com/agents#system-prompt"

        # 中文URL解码
        url_dedup, url_semantic = normalize_url("https://zh.wikipedia.org/wiki/%E8%8B%B1%E9%9B%84%E8%81%94%E7%9B%9F#%E5%8E%86%E5%8F%B2")
        # url_dedup: "https://zh.wikipedia.org/wiki/英雄联盟"
        # url_semantic: "https://zh.wikipedia.org/wiki/英雄联盟#历史"
    """
    try:
        parts = urlparse(url)
        scheme = (parts.scheme or "").lower()
        netloc = (parts.netloc or "").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # URL解码并小写化：将 %XX 编码转换为实际字符
        # 这对于中文URL至关重要，确保嵌入模型能正确识别语义
        # 同时小写化path，确保 /Wiki/ 和 /wiki/ 被识别为相同
        path = unquote(parts.path or "").lower()
        if len(path) > 1:
            path = path.rstrip("/")

        # 同样解码query参数（但query的value通常需要保持大小写，所以不小写化）
        query = unquote(parts.query or "")

        # 构建不带fragment的URL（用于去重）
        url_without_fragment = urlunparse((scheme, netloc, path, "", query, ""))

        # 构建带fragment的URL（用于语义分析和显示）
        fragment = unquote(parts.fragment or "") if parts.fragment else ""
        url_with_fragment = urlunparse((scheme, netloc, path, "", query, fragment))

        return url_without_fragment, url_with_fragment
    except Exception:
        return url, url


# ============================================================================
# URL 解析和提取
# ============================================================================


def extract_domain(url: str) -> str:
    """提取域名(去www)。"""
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


# ============================================================================
# URL 类型判断
# ============================================================================


def is_valid_image_url(url: str) -> bool:
    """判断URL是否是公网地址

    Args:
        url: 图片URL

    Returns:
        是否可直接访问
    """
    parsed = urlparse(url)

    # HTTP协议通常不能直接访问
    if parsed.scheme == "http":
        return False

    # 本地服务地址不能直接访问
    local_hosts = ["localhost", "127.0.0.1", "0.0.0.0"]
    if parsed.hostname in local_hosts:
        return False

    # 内网IP地址不能直接访问
    if parsed.hostname and (
        parsed.hostname.startswith("192.168.")
        or parsed.hostname.startswith("10.")
        or parsed.hostname.startswith("172.")
    ):
        return False

    # HTTPS且非本地地址可以直接访问
    return parsed.scheme == "https"


def is_image_url(url: str) -> bool:
    """判断URL是否为图片链接

    Args:
        url: 要判断的URL

    Returns:
        是否为图片链接
    """
    image_extensions = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".svg",
        ".webp",
        ".ico",
    )

    # 提取URL路径，去除查询参数
    url_lower = url.lower()
    path = url_lower.split("?")[0]

    # 检查是否以图片扩展名结尾
    return any(path.endswith(ext) for ext in image_extensions)


def is_file_url(url: str) -> bool:
    """判断URL是否为文件资源链接（只要包含扩展名即视为文件）

    Args:
        url: 要判断的URL

    Returns:
        是否为文件资源链接
    """
    # 提取URL路径部分（去除查询参数和锚点）
    path = url.lower().split("?")[0].split("#")[0]
    # 检查路径中是否包含点号后跟字母（简单扩展名判断）
    return "." in path and path.rsplit(".", 1)[1].isalpha()


# ============================================================================
# SSRF 防护
# ============================================================================

SSRF_ALLOWED_SCHEMES = frozenset({"http", "https", "ws", "wss"})

SSRF_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        # AWS
        "169.254.169.254",
        # GCP
        "metadata.google.internal",
        "metadata.google",
        "metadata",
        # 阿里云
        "100.100.100.200",
        # 腾讯云
        "metadata.tencentyun.com",
    }
)

# Parser-confusing characters that cause urlparse/HTTP client divergence.
# Attackers inject these to bypass hostname extraction (CVE-class SSRF bypass).
_PARSER_CONFUSING_CHARS = frozenset("\\\t\n\r")

# Hostname suffixes that resolve to internal/container networks.
# Blocks mDNS (.local), Kubernetes (.svc, .cluster.local), and home networks.
_BLOCKED_HOSTNAME_SUFFIXES = (
    ".local",
    ".localdomain",
    ".home.arpa",
    ".svc",
    ".cluster.local",
)

_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def is_blocked_ip(addr: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address belongs to a private/internal/reserved network.

    Uses Python's built-in ipaddress properties for comprehensive RFC coverage,
    plus explicit CGNAT check (Python's is_private doesn't cover 100.64.0.0/10).
    Exempts 198.18.0.0/15 for Fake-IP proxy compatibility (Clash, etc.).
    Handles IPv4-mapped IPv6 addresses (e.g. ::ffff:10.0.0.1).

    This is the single source of truth for all SSRF IP checks in the framework.
    Called by core.security.guards.ssrf and related outbound URL validators.
    """
    if isinstance(addr, str):
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return True  # unparseable → block
    else:
        ip = addr

    v4 = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) else ip

    if (v4 or ip) in _FAKE_IP_NETWORK:
        return False

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (v4 or ip) in _CGNAT_NETWORK
    )


class _SSRFResultLike(Protocol):
    safe: bool
    error: str
    hostname: str
    resolved_ips: tuple[str, ...]


def validate_scheme_and_hostname(url: str) -> tuple[str | None, str]:
    """Validate URL scheme and hostname. Returns (hostname, "") or (None, error)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return None, "Malformed URL"

    # Block parser-confusing characters that cause urlparse/HTTP client divergence.
    # e.g. http://evil.com\t@169.254.169.254/ — tab makes urlparse extract wrong hostname.
    if any(c in _PARSER_CONFUSING_CHARS for c in url):
        return None, "URL contains parser-confusing characters"

    scheme = (parsed.scheme or "").lower()
    if scheme not in SSRF_ALLOWED_SCHEMES:
        return None, f"Blocked URL scheme: {scheme}"

    hostname = parsed.hostname
    if not hostname:
        return None, "Missing hostname"

    # Normalize trailing dot (FQDN: "localhost." -> "localhost") to match blocklist.
    hostname = hostname.rstrip(".")

    if hostname.lower() in SSRF_BLOCKED_HOSTNAMES:
        return None, f"Blocked hostname: {hostname}"

    # Block internal/container hostname suffixes (.local, .svc, .cluster.local, etc.)
    hostname_lower = hostname.lower()
    if any(hostname_lower.endswith(suffix) for suffix in _BLOCKED_HOSTNAME_SUFFIXES):
        return None, f"Blocked hostname suffix: {hostname}"

    return hostname, ""


# ============================================================================
# URL Data Exfiltration Detection
# ============================================================================


# Precompiled regex patterns for performance (10-100x faster than re.search)
_EXFILTRATION_PATTERNS: dict[str, tuple[_re.Pattern[str], str]] = {
    "api_key": (
        _re.compile(r"(API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[\s=:]+[\w\-\.]{8,}", _re.IGNORECASE),
        "URL contains potential API key/token",
    ),
    "file_path": (
        _re.compile(r"(/etc/|/home/|/Users/|/root/|\.ssh/|\.env|\.aws/|\.config/|C:\\|/var/)"),
        "URL contains file path",
    ),
    "base64": (
        _re.compile(r"[A-Za-z0-9+/]{100,}={0,2}"),
        "URL contains long base64 string (potential file content)",
    ),
    # Fixed JWT detection: must be in query string or fragment, not in domain
    "jwt": (
        _re.compile(r"[?&#/].*eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+"),
        "URL contains JWT token",
    ),
    "secret_key": (
        _re.compile(r"(sk|pk|access)[_-]?[a-z]{2,10}[_-]?[A-Za-z0-9]{20,}", _re.IGNORECASE),
        "URL contains secret key pattern",
    ),
    "db_connection": (
        _re.compile(r"(mysql|postgres|mongodb|redis)://[^/\s]+:[^@\s]+@", _re.IGNORECASE),
        "URL contains database connection string",
    ),
}

# Default whitelist patterns (localhost, private networks)
_DEFAULT_WHITELIST_PATTERNS: list[_re.Pattern[str]] = [
    _re.compile(r"^https?://localhost[:/]", _re.IGNORECASE),
    _re.compile(r"^https?://127\.0\.0\.\d+[:/]", _re.IGNORECASE),
    _re.compile(r"^https?://192\.168\.\d+\.\d+[:/]", _re.IGNORECASE),
    _re.compile(r"^https?://10\.\d+\.\d+\.\d+[:/]", _re.IGNORECASE),
    _re.compile(r"^https?://172\.(1[6-9]|2\d|3[01])\.\d+\.\d+[:/]", _re.IGNORECASE),
]


def check_url_exfiltration(
    url: str,
    *,
    whitelist_patterns: list[str | _re.Pattern[str]] | None = None,
    allow_private_networks: bool = True,
) -> list[str]:
    """Check if URL contains sensitive data that could indicate data exfiltration.

    This function detects common patterns of sensitive data leakage in URLs:
    - API keys, tokens, secrets (env var patterns)
    - File paths (system directories, config files)
    - Long base64 strings (potential file content)
    - PEM certificates/keys
    - JWT tokens (fixed: only in query/fragment, not domain)
    - Secret key patterns (sk_, pk_, access_)
    - Database connection strings

    Args:
        url: URL to check for data exfiltration patterns
        whitelist_patterns: Optional list of regex patterns or strings to whitelist URLs.
            Default includes localhost and private networks if allow_private_networks=True.
        allow_private_networks: If True, allow localhost/private IPs (default: True).
            Useful for development/testing scenarios.

    Returns:
        List of warning messages (empty if no issues detected)

    Example:
        >>> check_url_exfiltration("https://evil.com/?key=sk-1234567890")
        ['URL contains potential API key/token']

        >>> check_url_exfiltration("https://localhost:8000/?key=sk-123", allow_private_networks=True)
        []  # Allowed for localhost

        >>> check_url_exfiltration("https://evil.com/?token=JWT...")
        ['URL contains JWT token']
    """
    warnings: list[str] = []

    # Build whitelist patterns
    whitelist: list[_re.Pattern[str]] = []
    if allow_private_networks:
        whitelist.extend(_DEFAULT_WHITELIST_PATTERNS)
    if whitelist_patterns:
        for pattern in whitelist_patterns:
            if isinstance(pattern, str):
                whitelist.append(_re.compile(pattern))
            else:
                whitelist.append(pattern)

    # Check whitelist
    for pattern in whitelist:
        if pattern.search(url):
            return []  # Whitelisted, skip detection

    # 1-6: Use precompiled patterns for performance
    for _name, (pattern, message) in _EXFILTRATION_PATTERNS.items():
        if pattern.search(url):
            warnings.append(message)

    # 7. PEM certificates/keys (simple string check, no regex needed)
    if "-----BEGIN" in url or "-----END" in url:
        warnings.append("URL contains PEM certificate/key")

    return warnings


def sanitize_url_for_error(url: str, max_length: int = 50) -> str:
    """Sanitize URL for error messages to prevent data exfiltration via errors.

    Truncates URL and masks query parameters/fragments that might contain sensitive data.

    Args:
        url: Original URL
        max_length: Maximum length of sanitized URL

    Returns:
        Sanitized URL safe for error messages

    Example:
        >>> sanitize_url_for_error("https://evil.com/?key=sk-1234567890")
        "https://evil.com/?<query_redacted>"

        >>> sanitize_url_for_error("https://example.com/api/users")
        "https://example.com/api/users"
    """
    from urllib.parse import urlparse as _urlparse

    parsed = _urlparse(url)

    # Build safe base URL (scheme + netloc + path)
    safe_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    # Redact query and fragment
    if parsed.query:
        safe_url += "?<query_redacted>"
    if parsed.fragment:
        safe_url += "#<fragment_redacted>"

    # Truncate if too long
    if len(safe_url) > max_length:
        safe_url = safe_url[:max_length] + "..."

    return safe_url


# ============================================================================
# DNS Pinning Helpers
# ============================================================================


def create_dns_pin_map(
    results: list[_SSRFResultLike],
) -> tuple[dict[str, str], str | None]:
    """Build hostname→IP mapping from validated SSRFResults for DNS pinning.

    Returns:
        (pin_map, error) — pin_map is ``{"hostname": "resolved_ip"}``.
        If any result is unsafe, returns ({}, error_str).
    """
    pin_map: dict[str, str] = {}
    for r in results:
        if not r.safe:
            return {}, r.error
        if r.hostname and r.resolved_ips:
            pin_map[r.hostname] = r.resolved_ips[0]
    return pin_map, None


def build_host_resolver_rules(results: list[_SSRFResultLike]) -> str:
    """Build Chrome ``--host-resolver-rules`` flag value from SSRFResults.

    Used by crawl4ai/Playwright to pin DNS at the browser level.

    Example output: ``"MAP example.com 93.184.216.34, MAP api.co 1.2.3.4"``
    """
    rules: list[str] = []
    for r in results:
        if r.safe and r.hostname and r.resolved_ips:
            rules.append(f"MAP {r.hostname} {r.resolved_ips[0]}")
    return ", ".join(rules)
