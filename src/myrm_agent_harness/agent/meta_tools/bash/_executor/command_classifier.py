"""Bash命令分类器 - 用于审计日志分类

[INPUT]

[OUTPUT]
- CommandClassifier: 命令分类器类
- CommandType: 命令类型枚举
- RiskLevel: 风险级别枚举

[POS]
Command classifier. Auto-classifies commands by type (READ/WRITE/DANGEROUS/NETWORK/GIT/SEARCH/PYTHON/SKILL) and risk level (LOW/MEDIUM/HIGH) using pattern matching.

"""

import re
from enum import StrEnum
from typing import ClassVar


class CommandType(StrEnum):
    """命令类型枚举"""

    READ = "READ"  # 只读命令（cat, head, tail, less, more, grep等）
    WRITE = "WRITE"  # 写入命令（cp, mv, rm, mkdir, touch, echo > 等）
    DANGEROUS = "DANGEROUS"  # 危险命令（rm -rf, dd, mkfs, chmod 777等）
    NETWORK = "NETWORK"  # 网络命令（curl, wget, ssh, scp等）
    GIT = "GIT"  # Git命令（git commit, git push等）
    SEARCH = "SEARCH"  # 搜索命令（grep, rg, ag, find等）
    PYTHON = "PYTHON"  # Python命令（python, python3等）
    SKILL = "SKILL"  # 技能调用（通过Python脚本调用技能）
    UNKNOWN = "UNKNOWN"  # 未知命令


class RiskLevel(StrEnum):
    """风险级别枚举"""

    LOW = "LOW"  # 低风险（只读命令、搜索命令）
    MEDIUM = "MEDIUM"  # 中风险（写入命令、网络命令、Git命令）
    HIGH = "HIGH"  # 高风险（危险命令）


class CommandClassifier:
    """命令分类器

    使用白名单匹配方式对命令进行分类。分类基于命令名称（第一个单词）。
    """

    # 只读命令白名单
    READ_COMMANDS: ClassVar[set[str]] = {
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "view",
        "bat",
        "xxd",
        "strings",
        "file",
        "stat",
        "ls",
        "dir",
        "tree",
        "pwd",
        "whoami",
        "id",
        "groups",
        "env",
        "printenv",
    }

    # 搜索命令白名单
    SEARCH_COMMANDS: ClassVar[set[str]] = {
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "ag",
        "ack",
        "find",
        "locate",
        "which",
        "whereis",
        "command",
    }

    # 写入命令白名单
    WRITE_COMMANDS: ClassVar[set[str]] = {
        "cp",
        "mv",
        "rm",
        "mkdir",
        "rmdir",
        "touch",
        "ln",
        "chown",
        "chgrp",
        "chmod",
        "chattr",
        "install",
        "tar",
        "zip",
        "unzip",
        "gzip",
        "gunzip",
        "bzip2",
        "bunzip2",
        "xz",
        "unxz",
        "sed",
        "awk",
        "tee",
        "dd",
    }

    # 危险命令正则模式（需要更精细的匹配）
    DANGEROUS_PATTERNS: ClassVar[list[str]] = [
        r"rm\s+-[rf]*rf",  # rm -rf
        r"rm\s+-[rf]*fr",  # rm -fr
        r"dd\s+",  # dd命令
        r"mkfs\.",  # mkfs.*
        r"chmod\s+777",  # chmod 777
        r"chmod\s+666",  # chmod 666
        r"chown\s+.*root",  # chown ... root
        r">\s*/dev/sd[a-z]",  # > /dev/sda
        r":\(\)\{\s*:\|:\s*&\s*\};:",  # fork bomb
    ]

    # 网络命令白名单
    NETWORK_COMMANDS: ClassVar[set[str]] = {
        "curl",
        "wget",
        "ssh",
        "scp",
        "sftp",
        "ftp",
        "rsync",
        "nc",
        "netcat",
        "telnet",
        "ping",
        "traceroute",
        "mtr",
        "dig",
        "nslookup",
        "host",
        "nmap",
    }

    # Git命令白名单
    GIT_COMMANDS: ClassVar[set[str]] = {
        "git",
    }

    # Python命令白名单
    PYTHON_COMMANDS: ClassVar[set[str]] = {
        "python",
        "python3",
        "python2",
        "py",
        "ipython",
        "pip",
        "pip3",
    }

    @classmethod
    def classify(cls, command: str) -> tuple[CommandType, RiskLevel]:
        """分类命令

        Args:
            command: 要分类的命令

        Returns:
            (CommandType, RiskLevel) 元组
        """
        if not command or not isinstance(command, str):
            return (CommandType.UNKNOWN, RiskLevel.LOW)

        # 去除前后空格
        command = command.strip()
        if not command:
            return (CommandType.UNKNOWN, RiskLevel.LOW)

        # 检测技能调用（包含"from skills."或"import skills."）
        if "from skills." in command or "import skills." in command:
            return (CommandType.SKILL, RiskLevel.LOW)

        # 检测危险命令（优先级最高）
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return (CommandType.DANGEROUS, RiskLevel.HIGH)

        # 提取第一个单词（命令名称）
        # 跳过环境变量赋值（VAR=value形式）
        words = command.split()
        command_name = None
        for word in words:
            # 跳过环境变量赋值
            if "=" in word and not word.startswith("-"):
                continue
            # 跳过选项
            if word.startswith("-"):
                continue
            # 提取命令名称（去除路径）
            command_name = word.rsplit("/", 1)[-1]
            break

        if not command_name:
            return (CommandType.UNKNOWN, RiskLevel.LOW)

        # 按优先级匹配命令类型
        if command_name in cls.READ_COMMANDS:
            return (CommandType.READ, RiskLevel.LOW)
        if command_name in cls.SEARCH_COMMANDS:
            return (CommandType.SEARCH, RiskLevel.LOW)
        if command_name in cls.PYTHON_COMMANDS:
            return (CommandType.PYTHON, RiskLevel.LOW)
        if command_name in cls.GIT_COMMANDS:
            return (CommandType.GIT, RiskLevel.MEDIUM)
        if command_name in cls.NETWORK_COMMANDS:
            return (CommandType.NETWORK, RiskLevel.MEDIUM)
        if command_name in cls.WRITE_COMMANDS:
            return (CommandType.WRITE, RiskLevel.MEDIUM)

        # 默认：未知命令，低风险
        return (CommandType.UNKNOWN, RiskLevel.LOW)
