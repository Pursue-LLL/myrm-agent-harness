"""敏感参数脱敏器 - 用于命令参数脱敏

[INPUT]

[OUTPUT]
- SensitiveParameterRedactor: 参数脱敏器类

[POS]
Command parameter redactor. Automatically redacts sensitive parameters (--token, --password, --api-key, etc.) when logging commands to audit trails.

"""

import re
from typing import ClassVar


class SensitiveParameterRedactor:
    """敏感参数脱敏器

    在记录命令时自动脱敏敏感参数值，防止凭证泄露到审计日志。
    """

    # 默认敏感参数关键词
    DEFAULT_SENSITIVE_KEYWORDS: ClassVar[list[str]] = [
        "token",
        "password",
        "passwd",
        "pwd",
        "api_key",
        "apikey",
        "api-key",
        "secret",
        "key",
        "auth",
        "credential",
        "credentials",
        "access_key",
        "access-key",
        "private_key",
        "private-key",
        "bearer",
        "authorization",
    ]

    def __init__(self, custom_keywords: list[str] | None = None):
        """初始化脱敏器

        Args:
            custom_keywords: 自定义敏感关键词列表（可选）
        """
        self.sensitive_keywords = set(self.DEFAULT_SENSITIVE_KEYWORDS)
        if custom_keywords:
            self.sensitive_keywords.update(k.lower() for k in custom_keywords)

        # 构建敏感参数正则模式
        # 匹配形式：
        # 1. --token=value
        # 2. --token value
        # 3. -t value
        # 4. env VAR=value（环境变量）
        keywords_pattern = "|".join(re.escape(k) for k in self.sensitive_keywords)
        self._param_patterns = [
            # --token=value 或 --token="value"
            re.compile(rf"--({keywords_pattern})[=\s]+([\"']?)([^\s\"']+)\2", re.IGNORECASE),
            # -t value 或 -t "value"
            re.compile(r"-[a-zA-Z]\s+([\"']?)([^\s\"']+)\1"),
            # 环境变量 TOKEN=value
            re.compile(rf"({keywords_pattern})[=]([\"']?)([^\s\"']+)\2", re.IGNORECASE),
        ]

    def redact(self, command: str) -> str:
        """脱敏命令中的敏感参数

        Args:
            command: 要脱敏的命令

        Returns:
            脱敏后的命令
        """
        if not command or not isinstance(command, str):
            return command

        redacted = command

        # 应用第一个模式：--token=value
        def replace_param_eq(match: re.Match[str]) -> str:
            param_name = match.group(1)
            return f"--{param_name}=***REDACTED***"

        redacted = self._param_patterns[0].sub(replace_param_eq, redacted)

        # 应用第二个模式：-t value（短选项）
        # 注意：这个比较激进，可能误判。只在前面有敏感关键词时才脱敏
        words = redacted.split()
        for i, word in enumerate(words):
            if word.startswith("-") and not word.startswith("--") and i + 1 < len(words):
                # 检查前面是否有敏感关键词
                prev_text = " ".join(words[:i])
                if any(keyword in prev_text.lower() for keyword in self.sensitive_keywords):
                    words[i + 1] = "***REDACTED***"
        redacted = " ".join(words)

        # 应用第三个模式：TOKEN=value（环境变量）
        def replace_env(match: re.Match[str]) -> str:
            var_name = match.group(1)
            return f"{var_name}=***REDACTED***"

        redacted = self._param_patterns[2].sub(replace_env, redacted)

        return redacted
