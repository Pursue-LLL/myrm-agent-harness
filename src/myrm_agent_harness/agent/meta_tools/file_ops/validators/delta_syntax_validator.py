"""增量容错语法校验器 (Delta Syntax Validator)

拦截文件写入操作（Create / Edit），使用轻量级内存解析器对 Python、JSON、YAML、TOML
等进行 0-overhead 语法校验。
仅暴露本次操作“新引入”的错误，如果原文件已有语法错误则放行（防发散）。

[INPUT]
- None (Self-contained in-process linters)

[OUTPUT]
- DeltaSyntaxValidator: 增量容错校验器类

[POS]
In-memory delta syntax validator. Provides zero-overhead syntax checking for structural languages, surfacing only newly introduced errors.
"""

import ast
import json
import os
import re
from collections.abc import Callable

# Type alias for linter function: takes file content, returns (is_success, error_message)
LinterFunc = Callable[[str], tuple[bool, str]]

def _strip_line_col(err_str: str) -> str:
    """提取错误特征签名，抹除可能偏移的行号/列号坐标"""
    s = re.sub(r'\(?line \d+(?:, column \d+)?\)?', '', err_str, flags=re.IGNORECASE)
    s = re.sub(r'line \d+ column \d+', '', s, flags=re.IGNORECASE)
    return s.strip()

def _lint_json_inproc(content: str) -> tuple[bool, str]:
    try:
        json.loads(content)
        return True, ""
    except json.JSONDecodeError as e:
        return False, f"JSONDecodeError: {e.msg} (line {e.lineno}, column {e.colno})"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

def _lint_yaml_inproc(content: str) -> tuple[bool, str]:
    try:
        import yaml
    except ImportError:
        return True, "__SKIP__"
    try:
        yaml.safe_load(content)
        return True, ""
    except yaml.YAMLError as e:
        return False, f"YAMLError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

def _lint_toml_inproc(content: str) -> tuple[bool, str]:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            return True, "__SKIP__"
    try:
        tomllib.loads(content)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

def _lint_python_inproc(content: str) -> tuple[bool, str]:
    try:
        ast.parse(content)
        return True, ""
    except SyntaxError as e:
        loc = f" (line {e.lineno}, column {e.offset})" if e.lineno else ""
        return False, f"{type(e).__name__}: {e.msg}{loc}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

LINTERS_INPROC: dict[str, LinterFunc] = {
    ".py": _lint_python_inproc,
    ".json": _lint_json_inproc,
    ".yaml": _lint_yaml_inproc,
    ".yml": _lint_yaml_inproc,
    ".toml": _lint_toml_inproc,
}

class DeltaSyntaxValidator:
    """增量语法校验器

    使用内存级别（in-process）的解析器快速校验文件内容的语法。
    如果有修改前的旧内容，则执行增量错误分析（Set-Difference）。
    """

    @staticmethod
    def validate(path: str, post_content: str, pre_content: str | None = None) -> None:
        """执行增量语法校验

        Args:
            path: 文件路径
            post_content: 写入后的文件内容
            pre_content: 写入前的文件内容。若是新建文件或不关心旧错误，传 None

        Raises:
            ValueError: 发现**新引入**的语法错误时抛出异常，阻止保存
        """
        ext = os.path.splitext(path)[1].lower()
        linter = LINTERS_INPROC.get(ext)
        if not linter:
            return  # No in-process linter for this extension

        # 1. 校验写入后的代码（Hot Path）
        post_ok, post_err = linter(post_content)
        if post_ok or post_err == "__SKIP__":
            return  # 没错误，或者由于依赖缺失无法校验

        # 2. 如果没提供旧代码，所有的错误都是致命错误
        if pre_content is None:
            raise ValueError(
                f"Syntax validation failed for {path}:\n{post_err}\n"
                f"Please fix the syntax error before saving."
            )

        # 3. 提供旧代码了，执行增量校验（Delta Lint）
        pre_ok, pre_err = linter(pre_content)
        if pre_ok or pre_err == "__SKIP__" or not pre_err:
            # 原来的代码是完全正确的，那么 post_err 全是新引入的错误
            raise ValueError(
                f"New syntax errors introduced in {path}:\n{post_err}\n"
                f"Please fix the error before saving."
            )

        # 4. 原代码也有错，新代码也有错，对比两个错误的差异（Set-Difference）
        # 满分优化：使用 _strip_line_col 清洗掉可能因为大模型加减空行而偏移的坐标
        # 只比对纯粹的“错误特征签名”
        pre_signatures = {_strip_line_col(line) for line in pre_err.splitlines() if line.strip()}

        # 为了给大模型报出带有准确行号的错误，我们保留原始的 post_lines 用于抛错
        # 但过滤条件是：它的“错误特征”不能存在于老错误里
        post_lines_to_report = [
            line for line in post_err.splitlines()
            if line.strip() and _strip_line_col(line) not in pre_signatures
        ]

        if not post_lines_to_report:
            # 新代码的错误特征，在老代码里全部都有，证明不是这次引入的
            # 仅仅是老错误被挤到了新的行，放行！不干扰大模型当前的任务
            return

        # 有新引入的独立错误
        new_errors_str = "\n".join(post_lines_to_report)
        raise ValueError(
            f"New syntax errors introduced in {path} (pre-existing errors filtered out):\n"
            f"{new_errors_str}\n"
            f"Please fix the newly introduced error before saving."
        )
