"""沙箱隔离环境多模态依赖特征嗅探模块。

自动分析克隆仓库的文件树结构，通过分级优先级管道精确识别：
MCP 服务、原生 Skill、Python 包或 Node.js 扩展，并嗅探依赖与本地编译标记。

[INPUT]
- __future__
- json
- dataclasses
- enum
- pathlib
- typing

[OUTPUT]
- PluginProjectKind
- ProjectDetectionResult
- SandboxDependencySniffer

[POS]
沙箱隔离环境多模态依赖特征嗅探模块。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar


class PluginProjectKind(StrEnum):
    """插件项目类型枚举。"""

    MCP_SERVER = "mcp_server"
    SKILL = "skill"
    PYTHON_PACKAGE = "python_package"
    NODE_PACKAGE = "node_package"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProjectDetectionResult:
    """项目依赖嗅探与类型推断结果实体。"""

    kind: PluginProjectKind
    manifest_file: str | None
    declared_dependencies: tuple[str, ...]
    install_command: str | None
    entry_file: str | None
    has_native_extensions: bool


class SandboxDependencySniffer:
    """沙箱依赖嗅探器。"""

    _NATIVE_EXTENSIONS: ClassVar[set[str]] = {".c", ".cpp", ".cc", ".cxx", ".rs", ".go"}

    @classmethod
    def check_has_native_extensions(cls, project_dir: Path) -> bool:
        """检查仓库内是否包含需要本地 C/C++/Rust 编译的原生代码文件。"""
        try:
            for item in project_dir.rglob("*"):
                if item.is_file() and item.suffix.lower() in cls._NATIVE_EXTENSIONS:
                    return True
        except Exception:
            pass
        return False

    @classmethod
    def sniff(cls, project_dir: Path) -> ProjectDetectionResult:
        """分级优先级嗅探管道：MCP > Skill > Python > Node.js。"""
        has_native = cls.check_has_native_extensions(project_dir)

        # 1. 优先级 1: MCP Server 规范
        mcp_candidates = ["mcp.json", ".mcp.json", "mcp-server.json"]
        for cand in mcp_candidates:
            cand_path = project_dir / cand
            if cand_path.is_file():
                return ProjectDetectionResult(
                    kind=PluginProjectKind.MCP_SERVER,
                    manifest_file=cand,
                    declared_dependencies=(),
                    install_command=None,
                    entry_file=cand,
                    has_native_extensions=has_native,
                )

        # 2. 优先级 2: 原生独立 Skill 规范
        skill_path = project_dir / "SKILL.md"
        if skill_path.is_file():
            return ProjectDetectionResult(
                kind=PluginProjectKind.SKILL,
                manifest_file="SKILL.md",
                declared_dependencies=(),
                install_command=None,
                entry_file="SKILL.md",
                has_native_extensions=has_native,
            )

        # 3. 优先级 3: Python 项目探测
        pyproject_path = project_dir / "pyproject.toml"
        requirements_path = project_dir / "requirements.txt"
        setup_path = project_dir / "setup.py"

        if pyproject_path.is_file() or requirements_path.is_file() or setup_path.is_file():
            manifest = "pyproject.toml" if pyproject_path.is_file() else (
                "requirements.txt" if requirements_path.is_file() else "setup.py"
            )
            deps: list[str] = []
            if requirements_path.is_file():
                try:
                    for line in requirements_path.read_text(encoding="utf-8").splitlines():
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#"):
                            deps.append(stripped)
                except Exception:
                    pass

            return ProjectDetectionResult(
                kind=PluginProjectKind.PYTHON_PACKAGE,
                manifest_file=manifest,
                declared_dependencies=tuple(deps[:50]),
                install_command="uv pip install --only-binary :all: -r requirements.txt"
                if requirements_path.is_file()
                else "uv pip install --only-binary :all: .",
                entry_file="main.py" if (project_dir / "main.py").exists() else None,
                has_native_extensions=has_native,
            )

        # 4. 优先级 4: Node.js 项目探测
        pkg_path = project_dir / "package.json"
        if pkg_path.is_file():
            node_deps: list[str] = []
            entry: str | None = None
            try:
                data = json.loads(pkg_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    entry = data.get("main")
                    pkg_deps = data.get("dependencies", {})
                    if isinstance(pkg_deps, dict):
                        node_deps.extend(list(pkg_deps.keys()))
            except Exception:
                pass

            return ProjectDetectionResult(
                kind=PluginProjectKind.NODE_PACKAGE,
                manifest_file="package.json",
                declared_dependencies=tuple(node_deps[:50]),
                install_command="bun install --production",
                entry_file=entry or "index.js",
                has_native_extensions=has_native,
            )

        # 5. 未知类型
        return ProjectDetectionResult(
            kind=PluginProjectKind.UNKNOWN,
            manifest_file=None,
            declared_dependencies=(),
            install_command=None,
            entry_file=None,
            has_native_extensions=has_native,
        )

    sniff_directory = sniff
