"""Expected-tail verified appends for append-only segment files.

Guards a checkpoint or log file against concurrent truncation and out-of-order
writes: the caller states the tail it believes the file ends with, and the append
is refused instead of corrupting the file when that belief is wrong.

[INPUT]
- pathlib.Path (POS: 目标追加文件)
- os (POS: fsync 落盘保证)

[OUTPUT]
- TailMismatchError: 期望尾部与实际尾部不一致
- AtomicSegmentAppender: 换行符标准化 + 尾部校验 + fsync 的原子追加器

[POS]
Write-side primitive of bounded segment execution. Deliberately synchronous and
dependency-free so it can run inside the job supervisor's critical section.
"""

from __future__ import annotations

import os
from pathlib import Path


class TailMismatchError(Exception):
    """当文件末尾与期望 expectedTail 不一致时抛出，表明发生并发冲突或乱序写。"""


class AtomicSegmentAppender:
    """带期望末尾校验与换行符标准化的原子追加器。"""

    @staticmethod
    def normalize_newlines(text: str) -> str:
        """统一换行符为 \\n 杜绝多端换行符歧义。"""
        return text.replace("\r\n", "\n").replace("\r", "\n")

    @classmethod
    def append_with_tail_check(
        cls,
        file_path: Path,
        content: str,
        expected_tail: str | None = None,
    ) -> int:
        """在文件末尾原子追加内容，严格校验期望尾部。

        返回写入后的新文件总字节数。
        """
        normalized_content = cls.normalize_newlines(content)
        if not normalized_content.endswith("\n"):
            normalized_content += "\n"

        file_path.parent.mkdir(parents=True, exist_ok=True)

        if not file_path.exists():
            if expected_tail is not None and expected_tail != "":
                raise TailMismatchError(f"File {file_path} does not exist, but expected tail: {expected_tail!r}")
            file_path.write_text(normalized_content, encoding="utf-8")
            return file_path.stat().st_size

        # 存在文件时，校验 tail
        if expected_tail is not None:
            normalized_expected = cls.normalize_newlines(expected_tail)
            tail_len = len(normalized_expected.encode("utf-8"))
            file_size = file_path.stat().st_size
            read_size = min(file_size, max(tail_len * 2, 512))

            with open(file_path, "rb") as f:
                if file_size > read_size:
                    f.seek(file_size - read_size)
                raw_tail = f.read().decode("utf-8", errors="ignore")

            normalized_current_tail = cls.normalize_newlines(raw_tail)
            if not normalized_current_tail.endswith(normalized_expected):
                raise TailMismatchError(
                    f"Tail mismatch in {file_path}: expected ending {normalized_expected!r}, "
                    f"actual ending {normalized_current_tail[-len(normalized_expected) :]!r}"
                )

        # 执行安全追加
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(normalized_content)
            f.flush()
            os.fsync(f.fileno())

        return file_path.stat().st_size
