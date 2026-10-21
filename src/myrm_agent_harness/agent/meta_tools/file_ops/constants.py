"""Text Editor 常量定义

包含文件大小限制、格式化常量和路径解析模式。

[INPUT]
- (none)

[OUTPUT]
- (none)

[POS]
Constants.
"""

import re

# 文件大小限制
MAX_FILE_READ_SIZE_BYTES = 10 * 1024 * 1024  # 最大读取文件大小 10MB
MAX_FILE_WRITE_SIZE_BYTES = 5 * 1024 * 1024  # 最大写入文件大小 5MB（工件限制）
MAX_FILE_READ_SIZE_MB = MAX_FILE_READ_SIZE_BYTES / (1024 * 1024)
MAX_FILE_WRITE_SIZE_MB = MAX_FILE_WRITE_SIZE_BYTES / (1024 * 1024)
MAX_FILE_SIZE_MB = MAX_FILE_READ_SIZE_MB  # 用于错误消息显示

# 格式化常量
LINE_NUMBER_WIDTH = 6  # 行号显示宽度
SEPARATOR_WIDTH = 60  # 分隔符宽度

# 路径行号范围解析正则：file.py:1-50 或 file.py:100-
PATH_RANGE_PATTERN = re.compile(r"^(.+):(\d+)-(\d*)$")
