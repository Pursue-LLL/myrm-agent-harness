"""Multi-language AST and code symbol search tool.

[INPUT]
- ast (POS: Native Python AST parser)
- re (POS: Fast regex pattern matching for multi-language symbols)
- pathlib::Path (POS: Safe filesystem path resolution)
- langchain.tools::tool (POS: LangChain tool decorator)
- pydantic::BaseModel, Field (POS: Parameter validation schema)
- agent.config.file_io::FileIOConfig (POS: I/O limits configuration)
- agent.meta_tools._context_recovery::ensure_executor (POS: ContextVar recovery for sandbox executor)

[OUTPUT]
- AstSymbolInput: Schema for ast_symbol_search_tool arguments
- create_ast_symbol_search_tool: Factory to create the code symbol extraction tool

[POS]
Lightweight, zero-daemon multi-language code structure and symbol search tool.
Extracts class/function/interface/method outlines and symbol definitions for Python,
TypeScript, JavaScript, Go, Rust, and other languages without running heavy LSP servers.
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.config import DEFAULT_FILE_IO_CONFIG, FileIOConfig
from myrm_agent_harness.agent.meta_tools._context_recovery import ensure_executor
from myrm_agent_harness.utils.errors import ToolError

from .fallback_discovery import collect_candidate_files
from .path_hint import format_path_not_found_hint, suggest_similar_paths

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

SymbolKind = Literal["class", "interface", "function", "method", "type", "struct", "enum", "constant"]


@dataclass(frozen=True, slots=True)
class CodeSymbol:
    name: str
    kind: SymbolKind
    line: int
    signature: str
    docstring_summary: str | None = None
    container: str | None = None


# Supported file extensions and their language families
_LANG_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
}


def _extract_python_symbols(source: str) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _extract_regex_symbols(source, "python")

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node)
            doc_summary = doc.strip().split("\n")[0][:100] if doc else None
            bases = [ast.unparse(b) for b in node.bases]
            sig = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
            symbols.append(
                CodeSymbol(
                    name=node.name,
                    kind="class",
                    line=node.lineno,
                    signature=sig,
                    docstring_summary=doc_summary,
                )
            )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_doc = ast.get_docstring(item)
                    m_doc_summary = m_doc.strip().split("\n")[0][:100] if m_doc else None
                    prefix = "async def " if isinstance(item, ast.AsyncFunctionDef) else "def "
                    args_str = ast.unparse(item.args)
                    return_str = f" -> {ast.unparse(item.returns)}" if item.returns else ""
                    m_sig = f"{prefix}{item.name}({args_str}){return_str}"
                    symbols.append(
                        CodeSymbol(
                            name=item.name,
                            kind="method",
                            line=item.lineno,
                            signature=m_sig,
                            docstring_summary=m_doc_summary,
                            container=node.name,
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            doc_summary = doc.strip().split("\n")[0][:100] if doc else None
            prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
            args_str = ast.unparse(node.args)
            return_str = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            sig = f"{prefix}{node.name}({args_str}){return_str}"
            symbols.append(
                CodeSymbol(
                    name=node.name,
                    kind="function",
                    line=node.lineno,
                    signature=sig,
                    docstring_summary=doc_summary,
                )
            )
    return symbols


_PATTERNS: dict[str, list[tuple[re.Pattern[str], SymbolKind]]] = {
    "typescript": [
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z0-9_$]+)(?:<[^>]+>)?(?:\s+extends\s+[^{]+)?(?:\s+implements\s+[^{]+)?"), "class"),
        (re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z0-9_$]+)(?:<[^>]+>)?(?:\s+extends\s+[^{]+)?"), "interface"),
        (re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z0-9_$]+)(?:<[^>]+>)?\s*="), "type"),
        (re.compile(r"^\s*(?:export\s+)?enum\s+([A-Za-z0-9_$]+)"), "enum"),
        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\([^)]*\)"), "function"),
        (re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*(?::\s*[^=]+)?=>"), "function"),
    ],
    "javascript": [
        (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z0-9_$]+)"), "class"),
        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\("), "function"),
        (re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"), "function"),
    ],
    "go": [
        (re.compile(r"^type\s+([A-Za-z0-9_]+)\s+struct"), "struct"),
        (re.compile(r"^type\s+([A-Za-z0-9_]+)\s+interface"), "interface"),
        (re.compile(r"^func\s+\(\s*[^)]+\s*\)\s*([A-Za-z0-9_]+)\s*\("), "method"),
        (re.compile(r"^func\s+([A-Za-z0-9_]+)\s*\("), "function"),
    ],
    "rust": [
        (re.compile(r"^\s*(?:pub\s+)?(?:struct)\s+([A-Za-z0-9_]+)"), "struct"),
        (re.compile(r"^\s*(?:pub\s+)?(?:enum)\s+([A-Za-z0-9_]+)"), "enum"),
        (re.compile(r"^\s*(?:pub\s+)?(?:trait)\s+([A-Za-z0-9_]+)"), "interface"),
        (re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)\s*\("), "function"),
    ],
    "python": [
        (re.compile(r"^\s*class\s+([A-Za-z0-9_]+)"), "class"),
        (re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z0-9_]+)\s*\("), "function"),
    ],
}


def _extract_regex_symbols(source: str, lang: str) -> list[CodeSymbol]:
    symbols: list[CodeSymbol] = []
    patterns = _PATTERNS.get(lang, _PATTERNS.get("typescript", []))
    lines = source.splitlines()

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#") or stripped.startswith("/*"):
            continue

        for pat, kind in patterns:
            match = pat.match(line)
            if match:
                name = match.group(1)
                sig = stripped.split("{")[0].strip() if "{" in stripped else stripped
                symbols.append(
                    CodeSymbol(
                        name=name,
                        kind=kind,
                        line=idx,
                        signature=sig[:120],
                    )
                )
                break
    return symbols


def extract_symbols_from_code(source: str, filename: str) -> list[CodeSymbol]:
    ext = Path(filename).suffix.lower()
    lang = _LANG_EXTENSIONS.get(ext, "typescript")
    if lang == "python":
        return _extract_python_symbols(source)
    return _extract_regex_symbols(source, lang)


class AstSymbolInput(BaseModel):
    """AST 代码符号搜索工具输入参数"""

    path: str = Field(default=".", description="目标文件路径或要扫描的目录路径（默认当前工作区根目录）")
    query: str | None = Field(default=None, description="符号名称搜索关键词（如 'AuthService' 或 'login'）；传 None 时输出大纲")
    mode: Literal["outline", "find_symbols"] = Field(
        default="outline",
        description="'outline'：提取指定文件或目录的代码结构大纲；'find_symbols'：跨文件检索特定符号定义",
    )
    file_pattern: str = Field(default="*", description="目录扫描时的文件通配过滤（如 '*.py'、'*.ts'）")


def create_ast_symbol_search_tool(io_config: FileIOConfig | None = None) -> BaseTool:
    """创建多语言 AST 与代码符号结构检索工具"""
    io_cfg = io_config or DEFAULT_FILE_IO_CONFIG

    @tool(
        "ast_symbol_search_tool",
        description="""轻量多语言代码符号与结构大纲提取工具（零守护进程，毫秒级响应）。

用途：
- 快速了解代码文件或模块的类/接口/函数/方法大纲（避免全量读取大文件消耗过多 Token）
- 定位特定类、函数或接口在文件中的定义行号与签名
- Monorepo 或多模块代码库中的符号快速探索

支持语言：
- Python (原生 AST)、TypeScript、JavaScript、Go、Rust 等

模式：
- mode="outline": 提取文件或目录的代码结构大纲与函数/类签名
- mode="find_symbols": 检索包含 query 的符号定义与所在行号
""",
        args_schema=AstSymbolInput,
    )
    async def ast_symbol_func(
        path: str = ".",
        query: str | None = None,
        mode: Literal["outline", "find_symbols"] = "outline",
        file_pattern: str = "*",
        *,
        config: RunnableConfig,
    ) -> str:
        executor = ensure_executor(config)
        resolved = await executor.resolve_path(path)
        p = Path(resolved)

        if not p.exists():
            parent = p.parent
            if parent.exists():
                candidates = suggest_similar_paths(p.name, parent)
                hint = format_path_not_found_hint(path, candidates)
                raise ToolError(hint)
            raise ToolError(f"Path not found: {path}")

        files_to_scan: list[Path] = []
        if p.is_file():
            files_to_scan.append(p)
        else:
            candidates = collect_candidate_files(
                search_root=p,
                file_pattern=file_pattern if file_pattern != "*" else "**/*",
                include_ignored=False,
                include_hidden=False,
                max_files=io_cfg.max_search_results,
            )
            files_to_scan.extend([c for c in candidates if c.suffix.lower() in _LANG_EXTENSIONS])

        if not files_to_scan:
            return f"No code files found under '{path}' matching pattern '{file_pattern}'."

        output_lines: list[str] = []
        total_symbols = 0
        target_query = query.strip().lower() if query else None

        for file_path in files_to_scan[:50]:
            try:
                rel_display = str(file_path.relative_to(p)) if p.is_dir() else str(file_path.name)
                content = file_path.read_text(encoding="utf-8", errors="replace")
                symbols = extract_symbols_from_code(content, file_path.name)

                if target_query:
                    symbols = [
                        s for s in symbols
                        if target_query in s.name.lower() or target_query in s.signature.lower()
                    ]

                if not symbols:
                    continue

                total_symbols += len(symbols)
                output_lines.append(f"📄 {rel_display}")
                for s in symbols:
                    container_prefix = f"{s.container}." if s.container else ""
                    doc_suffix = f"  # {s.docstring_summary}" if s.docstring_summary else ""
                    output_lines.append(f"  Line {s.line:4d} [{s.kind:9s}] {container_prefix}{s.signature}{doc_suffix}")
                output_lines.append("")
            except Exception as e:
                logger.debug("Failed to extract symbols from %s: %s", file_path, e)
                continue

        if not output_lines:
            if target_query:
                return f"No symbols found matching '{query}' in {len(files_to_scan)} files."
            return f"No symbols extracted from {len(files_to_scan)} files."

        summary = f"Found {total_symbols} symbols across {len(files_to_scan)} code files:\n\n"
        return summary + "\n".join(output_lines).strip()

    return ast_symbol_func
