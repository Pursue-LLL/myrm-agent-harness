"""自然语言单句 Git 仓库插件安装意图解析与 SSRF 安全拦截模块。

从用户普通对话文本中精准提取 Git/GitHub 仓库 URL，
并强制执行 HTTPS 协议白名单与私网 IP（RFC 1918 / 云元数据）强拦截，
杜绝内网穿透与恶意探测风险。

[INPUT]
- __future__
- ipaddress
- re
- socket
- dataclasses
- urllib

[OUTPUT]
- InsecureRepoUrlError
- ParsedRepoTarget
- RepoCoordinate
- IntentParseResult
- SafeRepoUrlValidator
- RepoIntentParser

[POS]
自然语言单句 Git 仓库插件安装意图解析与 SSRF 安全拦截模块。
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

# 权威开源代码托管白名单
_DEFAULT_ALLOWED_HOSTS: set[str] = {
    "github.com",
    "gitlab.com",
    "gitee.com",
    "bitbucket.org",
}

_URL_REGEX = re.compile(
    r"https?://[a-zA-Z0-9\-\.]+(?::[0-9]+)?/[a-zA-Z0-9_\-\./]+"
)
_INSTALL_INTENT_KEYWORDS: list[str] = [
    "安装",
    "使用",
    "配置",
    "帮我搞定",
    "接入",
    "装一下",
    "install",
    "use",
    "setup",
    "add plugin",
    "add skill",
]


class InsecureRepoUrlError(ValueError):
    """当目标仓库 URL 存在安全隐患（非 HTTPS、私网 IP、非法协议）时抛出。"""


@dataclass(frozen=True, slots=True)
class ParsedRepoTarget:
    """解析后的合法 Git 仓库目标实体。"""

    canonical_url: str
    host: str
    owner: str
    repo_name: str
    plugin_id: str

    @property
    def repo(self) -> str:
        """仓库名快捷别名。"""
        return self.repo_name

    @property
    def normalized_url(self) -> str:
        """规范化整洁仓库主页 URL。"""
        return f"https://{self.host}/{self.owner}/{self.repo_name}"


RepoCoordinate = ParsedRepoTarget


@dataclass(frozen=True)
class IntentParseResult:
    """意图解析结果。"""

    is_install_intent: bool
    target: ParsedRepoTarget | None
    raw_url: str | None
    reason: str


class SafeRepoUrlValidator:
    """Git 仓库安全校验器（防 SSRF 与私网越界）。"""

    @staticmethod
    def is_private_or_loopback_ip(ip_str: str) -> bool:
        """检查 IP 是否属于本地回环、RFC 1918 私网或云元数据地址段。"""
        try:
            ip = ipaddress.ip_address(ip_str)
            if ip.is_loopback or ip.is_link_local:
                return True
            if ip_str.startswith("169.254."):
                return True
            # 精准校验 RFC 1918 私网及特殊保留网段（规避透明代理 Fake-IP 198.18.0.0/15 误判）
            rfc1918_networks = (
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
                ipaddress.ip_network("127.0.0.0/8"),
                ipaddress.ip_network("0.0.0.0/8"),
            )
            return any(ip in net for net in rfc1918_networks)
        except ValueError:
            # 传入非 IP 格式的字符串（如纯域名 hostname），表示其不是 IP 字面量
            return False

    @classmethod
    def validate_and_parse(
        cls,
        raw_url: str,
        allowed_hosts: set[str] | None = None,
        allow_dns_resolution: bool = True,
    ) -> ParsedRepoTarget:
        """校验 URL 安全性并规范化解析出仓库坐标。"""
        parsed = urlparse(raw_url.strip())

        # 1. 协议严格限制：仅允许 HTTPS
        if parsed.scheme.lower() != "https":
            raise InsecureRepoUrlError(
                f"Scheme '{parsed.scheme}' is insecure. Protocol '{parsed.scheme}' is prohibited. Only 'https://' repositories are allowed."
            )

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise InsecureRepoUrlError("Invalid repository URL: missing hostname.")

        # 2. 域名白名单与格式校验
        hosts = allowed_hosts or _DEFAULT_ALLOWED_HOSTS
        if hostname not in hosts:
            if cls.is_private_or_loopback_ip(hostname):
                raise InsecureRepoUrlError(
                    f"Loopback or private network access is prohibited: '{hostname}'."
                )
            raise InsecureRepoUrlError(
                f"Host '{hostname}' is not in allowed repository hosts whitelist."
            )

        # 3. DNS 预检防 SSRF
        if allow_dns_resolution:
            try:
                addr_info = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
                for entry in addr_info:
                    sockaddr = entry[4]
                    ip_resolved = str(sockaddr[0]) if isinstance(sockaddr, tuple) and len(sockaddr) > 0 else str(sockaddr)
                    if cls.is_private_or_loopback_ip(ip_resolved):
                        raise InsecureRepoUrlError(
                            f"Host '{hostname}' resolved to prohibited private IP: {ip_resolved}"
                        )
            except socket.gaierror:
                pass  # 离线单测或无网环境允许跳过解析

        # 4. 提取 owner 与 repo_name
        path_segments = [seg for seg in parsed.path.strip("/").split("/") if seg]
        if len(path_segments) < 2:
            raise InsecureRepoUrlError(
                f"URL path '{parsed.path}' is invalid; must follow 'owner/repo' format."
            )

        owner = path_segments[0].strip()
        repo_name = path_segments[1].removesuffix(".git").strip()
        canonical_url = f"https://{hostname}/{owner}/{repo_name}.git"
        plugin_id = f"{owner.lower()}_{repo_name.lower()}".replace("-", "_")

        return ParsedRepoTarget(
            canonical_url=canonical_url,
            host=hostname,
            owner=owner,
            repo_name=repo_name,
            plugin_id=plugin_id,
        )


class RepoIntentParser:
    """自然语言单句仓库安装意图解析器。"""

    def __init__(self, validator: SafeRepoUrlValidator | None = None) -> None:
        self._validator = validator or SafeRepoUrlValidator()

    def parse_sentence(self, user_text: str) -> IntentParseResult:
        """从用户对话自然语言中解析插件安装意图与目标 URL。"""
        # 1. 检索是否存在 URL
        match = _URL_REGEX.search(user_text)
        if not match:
            return IntentParseResult(
                is_install_intent=False,
                target=None,
                raw_url=None,
                reason="No URL found in text",
            )

        raw_url = match.group(0)

        # 2. 检查安装意图动词
        text_lower = user_text.lower()
        has_intent = any(keyword in text_lower for keyword in _INSTALL_INTENT_KEYWORDS)
        if not has_intent:
            return IntentParseResult(
                is_install_intent=False,
                target=None,
                raw_url=raw_url,
                reason="URL found but lacks explicit installation intent keywords",
            )

        # 3. 校验并提取仓库坐标
        try:
            target = self._validator.validate_and_parse(raw_url)
            return IntentParseResult(
                is_install_intent=True,
                target=target,
                raw_url=raw_url,
                reason="Installation intent and secure repository URL confirmed",
            )
        except InsecureRepoUrlError as exc:
            return IntentParseResult(
                is_install_intent=False,
                target=None,
                raw_url=raw_url,
                reason=f"Security rejection: {exc}",
            )

    parse_install_intent = parse_sentence
