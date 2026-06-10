"""Human-readable bilingual explanations for shell commands in approval UI.

[INPUT]
- Command text (str), segment spans, risk levels

[OUTPUT]
- humanize_command: Bilingual dict {en: str, zh: str} plain-language explanation.

[POS]
Additive UX enhancement: translates shell command semantics into user-friendly
language for approval surfaces where dialog context may be absent (desktop OS
notifications, cron task approvals, audit log review).
"""

from __future__ import annotations

import shlex
from typing import TypedDict

from myrm_agent_harness.toolkits.code_execution.security.command_explainer.types import (
    CommandSpan,
    SpanRiskLevel,
)


class BilingualExplanation(TypedDict):
    en: str
    zh: str


_COMMAND_EXPLANATIONS: dict[str, BilingualExplanation] = {
    "curl": {"en": "Download content from a URL", "zh": "从网络地址下载内容"},
    "wget": {"en": "Download files from a URL", "zh": "从网络地址下载文件"},
    "rm": {"en": "Delete files or directories", "zh": "删除文件或目录"},
    "sudo": {"en": "Execute with admin privileges", "zh": "以管理员权限执行"},
    "apt": {"en": "Manage system packages (Debian/Ubuntu)", "zh": "管理系统软件包"},
    "apt-get": {"en": "Manage system packages (Debian/Ubuntu)", "zh": "管理系统软件包"},
    "yum": {"en": "Manage system packages (RHEL/CentOS)", "zh": "管理系统软件包"},
    "dnf": {"en": "Manage system packages (Fedora)", "zh": "管理系统软件包"},
    "brew": {"en": "Manage packages via Homebrew", "zh": "通过 Homebrew 管理软件包"},
    "pip": {"en": "Install Python packages", "zh": "安装 Python 包"},
    "pip3": {"en": "Install Python packages", "zh": "安装 Python 包"},
    "npm": {"en": "Manage Node.js packages", "zh": "管理 Node.js 包"},
    "npx": {"en": "Run a Node.js package command", "zh": "运行 Node.js 包命令"},
    "yarn": {"en": "Manage Node.js packages", "zh": "管理 Node.js 包"},
    "pnpm": {"en": "Manage Node.js packages", "zh": "管理 Node.js 包"},
    "bun": {"en": "Run/manage with Bun runtime", "zh": "使用 Bun 运行或管理"},
    "docker": {"en": "Manage Docker containers", "zh": "管理 Docker 容器"},
    "docker-compose": {"en": "Manage multi-container Docker apps", "zh": "管理多容器 Docker 应用"},
    "kubectl": {"en": "Manage Kubernetes cluster", "zh": "管理 Kubernetes 集群"},
    "systemctl": {"en": "Control system services", "zh": "控制系统服务"},
    "service": {"en": "Control system services", "zh": "控制系统服务"},
    "chmod": {"en": "Change file permissions", "zh": "修改文件权限"},
    "chown": {"en": "Change file ownership", "zh": "修改文件所有者"},
    "mv": {"en": "Move or rename files", "zh": "移动或重命名文件"},
    "cp": {"en": "Copy files or directories", "zh": "复制文件或目录"},
    "mkdir": {"en": "Create directories", "zh": "创建目录"},
    "kill": {"en": "Terminate a process", "zh": "终止进程"},
    "pkill": {"en": "Terminate processes by name", "zh": "按名称终止进程"},
    "reboot": {"en": "Restart the system", "zh": "重启系统"},
    "shutdown": {"en": "Shut down the system", "zh": "关闭系统"},
    "mount": {"en": "Mount a filesystem", "zh": "挂载文件系统"},
    "umount": {"en": "Unmount a filesystem", "zh": "卸载文件系统"},
    "dd": {"en": "Copy raw disk data", "zh": "复制原始磁盘数据"},
    "mkfs": {"en": "Format a disk partition", "zh": "格式化磁盘分区"},
    "iptables": {"en": "Configure firewall rules", "zh": "配置防火墙规则"},
    "ufw": {"en": "Configure firewall (UFW)", "zh": "配置防火墙"},
    "ssh": {"en": "Open a remote shell connection", "zh": "建立远程 Shell 连接"},
    "scp": {"en": "Copy files to/from remote host", "zh": "与远程主机传输文件"},
    "rsync": {"en": "Sync files to/from remote host", "zh": "同步远程文件"},
    "git": {"en": "Perform Git version control operation", "zh": "执行 Git 版本控制操作"},
    "python": {"en": "Run a Python script", "zh": "运行 Python 脚本"},
    "python3": {"en": "Run a Python script", "zh": "运行 Python 脚本"},
    "node": {"en": "Run a Node.js script", "zh": "运行 Node.js 脚本"},
    "cargo": {"en": "Build/manage Rust project", "zh": "构建/管理 Rust 项目"},
    "make": {"en": "Run build tasks", "zh": "运行构建任务"},
    "cmake": {"en": "Configure build system", "zh": "配置构建系统"},
    "tar": {"en": "Archive or extract files", "zh": "打包或解压文件"},
    "unzip": {"en": "Extract ZIP archive", "zh": "解压 ZIP 文件"},
    "sed": {"en": "Stream-edit file contents", "zh": "流式编辑文件内容"},
    "awk": {"en": "Process text with patterns", "zh": "按模式处理文本"},
    "crontab": {"en": "Edit scheduled tasks", "zh": "编辑计划任务"},
    "useradd": {"en": "Create a system user", "zh": "创建系统用户"},
    "userdel": {"en": "Delete a system user", "zh": "删除系统用户"},
    "passwd": {"en": "Change user password", "zh": "修改用户密码"},
    "openssl": {"en": "Perform cryptographic operations", "zh": "执行加密操作"},
    "certbot": {"en": "Manage SSL certificates", "zh": "管理 SSL 证书"},
    "nginx": {"en": "Control Nginx web server", "zh": "控制 Nginx 服务器"},
    "apachectl": {"en": "Control Apache web server", "zh": "控制 Apache 服务器"},
    "psql": {"en": "Run PostgreSQL commands", "zh": "执行 PostgreSQL 命令"},
    "mysql": {"en": "Run MySQL commands", "zh": "执行 MySQL 命令"},
    "redis-cli": {"en": "Run Redis commands", "zh": "执行 Redis 命令"},
    "mongosh": {"en": "Run MongoDB commands", "zh": "执行 MongoDB 命令"},
    "sh": {"en": "Execute a shell script", "zh": "执行 Shell 脚本"},
    "bash": {"en": "Execute a Bash script", "zh": "执行 Bash 脚本"},
    "zsh": {"en": "Execute a Zsh script", "zh": "执行 Zsh 脚本"},
    "eval": {"en": "Evaluate shell expression", "zh": "求值 Shell 表达式"},
    "exec": {"en": "Replace current process", "zh": "替换当前进程"},
    "source": {"en": "Load shell configuration", "zh": "加载 Shell 配置"},
    "ln": {"en": "Create file links", "zh": "创建文件链接"},
    "tee": {"en": "Write output to file and stdout", "zh": "将输出写入文件"},
    "xargs": {"en": "Execute command with piped arguments", "zh": "用管道参数执行命令"},
}

_CHAIN_AND_EXPLANATION: BilingualExplanation = {
    "en": "then",
    "zh": "然后",
}

_SUDO_PREFIX: BilingualExplanation = {
    "en": "with admin privileges",
    "zh": "以管理员权限",
}

_FALLBACK_EXPLANATION: BilingualExplanation = {
    "en": "Execute a shell command that requires your approval",
    "zh": "执行一条需要您授权的 Shell 命令",
}

_DOWNLOAD_COMMANDS = frozenset({"curl", "wget"})
_EXEC_COMMANDS = frozenset({"bash", "sh", "zsh", "eval", "source"})

_DANGEROUS_PIPE_EXPLANATION: BilingualExplanation = {
    "en": "Downloads and immediately executes remote code — high risk",
    "zh": "下载并立即执行远程代码 — 高风险",
}

_PARAM_AWARE_COMMANDS: dict[str, tuple[str, str]] = {
    "rm": ("Delete: {target}", "删除: {target}"),
    "pip": ("Install Python packages: {target}", "安装 Python 包: {target}"),
    "pip3": ("Install Python packages: {target}", "安装 Python 包: {target}"),
    "npm": ("npm {sub}: {target}", "npm {sub}: {target}"),
    "chmod": ("Change permissions to {target}", "修改权限为 {target}"),
    "chown": ("Change owner to {target}", "修改所有者为 {target}"),
    "mv": ("Move {target}", "移动 {target}"),
    "cp": ("Copy {target}", "复制 {target}"),
    "curl": ("Download from {target}", "从 {target} 下载"),
    "wget": ("Download from {target}", "从 {target} 下载"),
    "docker": ("docker {sub}", "docker {sub}"),
    "git": ("git {sub}", "git {sub}"),
    "ssh": ("Connect to {target}", "连接到 {target}"),
    "scp": ("Copy to/from {target}", "传输文件 {target}"),
    "kill": ("Terminate process {target}", "终止进程 {target}"),
    "pkill": ("Terminate processes: {target}", "终止进程: {target}"),
    "mkdir": ("Create directory: {target}", "创建目录: {target}"),
    "ln": ("Create link: {target}", "创建链接: {target}"),
    "sed": ("Edit: {target}", "编辑: {target}"),
}


def _extract_param_target(cmd: str, tokens: list[str]) -> str | None:
    """Extract the most meaningful user-visible argument from a command."""
    non_flag = [t for t in tokens[1:] if not t.startswith("-")]
    if not non_flag:
        return None

    if cmd in ("npm", "docker", "git", "kubectl"):
        return None

    if cmd in ("curl", "wget"):
        for t in non_flag:
            if t.startswith("http://") or t.startswith("https://"):
                return t
        return non_flag[-1]

    if cmd in ("rm", "mv", "cp", "mkdir", "chmod", "chown", "ln", "sed"):
        return non_flag[-1]

    if cmd in ("pip", "pip3"):
        for i, t in enumerate(tokens):
            if t == "install" and i + 1 < len(tokens):
                rest = [p for p in tokens[i + 1:] if not p.startswith("-")]
                return " ".join(rest) if rest else None
        return None

    if cmd in ("kill", "pkill"):
        return non_flag[0]

    if cmd in ("ssh", "scp"):
        return non_flag[0]

    return None


def _get_subcommand(cmd: str, tokens: list[str]) -> str | None:
    """Extract subcommand for multi-command tools."""
    if cmd not in ("npm", "docker", "git", "kubectl"):
        return None
    non_flag = [t for t in tokens[1:] if not t.startswith("-")]
    return non_flag[0] if non_flag else None


def _build_param_explanation(
    cmd: str, tokens: list[str], base_explanation: BilingualExplanation,
) -> BilingualExplanation:
    """Enrich explanation with parameter context when available."""
    templates = _PARAM_AWARE_COMMANDS.get(cmd)
    if not templates:
        return base_explanation

    target = _extract_param_target(cmd, tokens)
    sub = _get_subcommand(cmd, tokens)

    en_tpl, zh_tpl = templates

    if cmd in ("npm", "docker", "git", "kubectl"):
        if sub:
            target_for_sub = _extract_param_target(cmd, tokens)
            label = f"{sub} {target_for_sub}" if target_for_sub else sub
            return {
                "en": en_tpl.format(sub=sub, target=label),
                "zh": zh_tpl.format(sub=sub, target=label),
            }
        return base_explanation

    if target:
        truncated = target if len(target) <= 60 else target[:57] + "..."
        return {
            "en": en_tpl.format(target=truncated),
            "zh": zh_tpl.format(target=truncated),
        }

    return base_explanation


def _detect_dangerous_pipe(segments: list[str]) -> bool:
    """Detect download-to-exec pipeline patterns like `curl ... | bash`."""
    if len(segments) < 2:
        return False

    for i in range(len(segments) - 1):
        try:
            left_tokens = shlex.split(segments[i])
        except ValueError:
            left_tokens = segments[i].split()
        try:
            right_tokens = shlex.split(segments[i + 1])
        except ValueError:
            right_tokens = segments[i + 1].split()

        left_cmd = left_tokens[0].rsplit("/", 1)[-1] if left_tokens else ""
        right_cmd = right_tokens[0].rsplit("/", 1)[-1] if right_tokens else ""

        if left_cmd in _DOWNLOAD_COMMANDS and right_cmd in _EXEC_COMMANDS:
            return True

    return False


def _explain_segment(segment: str) -> BilingualExplanation | None:
    """Generate explanation for a single command segment."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()

    if not tokens:
        return None

    has_sudo = tokens[0] == "sudo"
    base_tokens = tokens[1:] if has_sudo else tokens
    if not base_tokens:
        return _COMMAND_EXPLANATIONS.get("sudo")

    base_cmd = base_tokens[0].rsplit("/", 1)[-1]
    explanation = _COMMAND_EXPLANATIONS.get(base_cmd)

    if explanation is None:
        return None

    explanation = _build_param_explanation(base_cmd, base_tokens, explanation)

    if has_sudo:
        return {
            "en": f"{explanation['en']} {_SUDO_PREFIX['en']}",
            "zh": f"{_SUDO_PREFIX['zh']}{explanation['zh']}",
        }

    return explanation


def humanize_command(
    command: str,
    spans: list[CommandSpan],
    risks: list[SpanRiskLevel],
) -> BilingualExplanation | None:
    """Generate a bilingual human-readable explanation for a shell command.

    Returns None if no meaningful explanation can be produced (all segments are
    safe or unrecognized).
    """
    if not spans or not risks or len(spans) != len(risks):
        return None

    has_unknown = any(r == "unknown" for r in risks)
    if not has_unknown:
        return None

    segments = [command[s["startIndex"]:s["endIndex"]] for s in spans]

    if _detect_dangerous_pipe(segments):
        return _DANGEROUS_PIPE_EXPLANATION

    explanations: list[BilingualExplanation | None] = [
        _explain_segment(seg) if risks[i] == "unknown" else None
        for i, seg in enumerate(segments)
    ]

    meaningful = [(i, exp) for i, exp in enumerate(explanations) if exp is not None]
    if not meaningful:
        return _FALLBACK_EXPLANATION

    if len(meaningful) == 1:
        return meaningful[0][1]

    en_parts: list[str] = []
    zh_parts: list[str] = []
    for idx, (i, exp) in enumerate(meaningful):
        if idx > 0:
            en_parts.append(_CHAIN_AND_EXPLANATION["en"])
            zh_parts.append(_CHAIN_AND_EXPLANATION["zh"])
        en_parts.append(exp["en"].lower() if idx > 0 else exp["en"])
        zh_parts.append(exp["zh"])

    return {
        "en": " ".join(en_parts),
        "zh": "".join(zh_parts),
    }
