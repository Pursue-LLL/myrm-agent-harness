"""Pre-defined CLI tool catalog.

Adding a tool = adding a ToolDefinition entry — pure data, no code change.

[INPUT]
.types::ToolDefinition (POS: CLI tool discovery data types)

[OUTPUT]
TOOL_CATALOG: pre-defined CLI tool catalog (~25 ToolDefinition entries with platform-specific install commands)

[POS]
CLI tool catalog data layer. Maintains the list of CLI tools recognizable by Agent, organized by category
(Media/Data/Search/Network/Dev/System/Document/Remote). Each tool can include install_hints for precise
install command suggestions in error messages.
"""

from __future__ import annotations

from .types import ToolDefinition

TOOL_CATALOG: tuple[ToolDefinition, ...] = (
    # ── Media ────────────────────────────────────────────────
    ToolDefinition(
        id="ffmpeg",
        bin_names=("ffmpeg",),
        desc_en="Audio/video processing (transcode, cut, merge, stream)",
        desc_zh="音视频Process（转码、剪切、Merge、流Process）",
        tags=frozenset({"streaming"}),
        install_hints={"Darwin": "brew install ffmpeg", "Linux": "apt install ffmpeg"},
    ),
    ToolDefinition(
        id="imagemagick",
        bin_names=("convert", "magick"),
        desc_en="Image processing (resize, convert, compose, annotate)",
        desc_zh="图像Process（缩放、FormatConvert、合成、标注）",
        install_hints={"Darwin": "brew install imagemagick", "Linux": "apt install imagemagick"},
    ),
    # ── Data ─────────────────────────────────────────────────
    ToolDefinition(
        id="jq",
        bin_names=("jq",),
        desc_en="JSON processor (query, filter, transform)",
        desc_zh="JSON Process器（Query、Filter、Convert）",
        tags=frozenset({"json_output"}),
        install_hints={"Darwin": "brew install jq", "Linux": "apt install jq", "Windows": "choco install jq"},
    ),
    ToolDefinition(
        id="yq",
        bin_names=("yq",),
        desc_en="YAML/JSON/TOML processor (query, convert between formats)",
        desc_zh="YAML/JSON/TOML Process器（Query、Format互转）",
        tags=frozenset({"json_output"}),
        install_hints={"Darwin": "brew install yq", "Linux": "snap install yq"},
    ),
    # ── Search ───────────────────────────────────────────────
    ToolDefinition(
        id="ripgrep",
        bin_names=("rg",),
        desc_en="Ultra-fast regex text search across files",
        desc_zh="超快 正则textSearch",
        tags=frozenset({"json_output"}),
        install_hints={
            "Darwin": "brew install ripgrep",
            "Linux": "apt install ripgrep",
            "Windows": "choco install ripgrep",
        },
    ),
    ToolDefinition(
        id="fd",
        bin_names=("fd", "fdfind"),
        desc_en="Fast file finder (modern alternative to find)",
        desc_zh="fastFile查找（find  现代替代）",
        install_hints={"Darwin": "brew install fd", "Linux": "apt install fd-find", "Windows": "choco install fd"},
    ),
    # ── Network ──────────────────────────────────────────────
    ToolDefinition(
        id="curl",
        bin_names=("curl",),
        desc_en="HTTP client (API calls, file download, multipart upload)",
        desc_zh="HTTP Client（API Call、FileDownload、Upload）",
        tags=frozenset({"json_output"}),
        install_hints={"Darwin": "brew install curl", "Linux": "apt install curl", "Windows": "choco install curl"},
    ),
    ToolDefinition(
        id="wget",
        bin_names=("wget",),
        desc_en="File downloader (recursive download, resume support)",
        desc_zh="FileDownload器（recursiveDownload、断点续传）",
        install_hints={"Darwin": "brew install wget", "Linux": "apt install wget", "Windows": "choco install wget"},
    ),
    # ── Development ──────────────────────────────────────────
    ToolDefinition(
        id="git",
        bin_names=("git",),
        desc_en="Version control (commit, branch, diff, log)",
        desc_zh="版本控制（提交、分支、差异、Log）",
        install_hints={"Darwin": "brew install git", "Linux": "apt install git", "Windows": "choco install git"},
    ),
    ToolDefinition(
        id="docker",
        bin_names=("docker",),
        desc_en="Container management (build, run, compose, images)",
        desc_zh="容器管理（Build、运行、编排、镜像）",
        tags=frozenset({"json_output"}),
        install_hints={"Darwin": "brew install --cask docker", "Linux": "apt install docker.io"},
    ),
    ToolDefinition(
        id="node",
        bin_names=("node",),
        desc_en="Node.js runtime (execute JS/TS scripts)",
        desc_zh="Node.js 运行时（Execute JS/TS 脚本）",
        install_hints={"Darwin": "brew install node", "Linux": "apt install nodejs"},
    ),
    ToolDefinition(
        id="python3",
        bin_names=("python3", "python"),
        desc_en="Python 3 runtime",
        desc_zh="Python 3 运行时",
        install_hints={"Darwin": "brew install python3", "Linux": "apt install python3"},
    ),
    ToolDefinition(
        id="pip",
        bin_names=("pip3", "pip"),
        desc_en="Python package installer",
        desc_zh="Python 包管理器",
        install_hints={"Darwin": "python3 -m ensurepip", "Linux": "apt install python3-pip"},
    ),
    ToolDefinition(
        id="uv",
        bin_names=("uv",),
        desc_en="Ultra-fast Python package manager (pip/venv alternative)",
        desc_zh="超快 Python 包管理器（pip/venv 替代）",
        install_hints={
            "Darwin": "curl -LsSf https://astral.sh/uv/install.sh | sh",
            "Linux": "curl -LsSf https://astral.sh/uv/install.sh | sh",
            "Windows": 'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"',
        },
    ),
    ToolDefinition(
        id="bun",
        bin_names=("bun",),
        desc_en="Fast JS runtime + package manager + bundler",
        desc_zh="高速 JS 运行时 + 包管理器 + 打包器",
        install_hints={
            "Darwin": "curl -fsSL https://bun.sh/install | bash",
            "Linux": "curl -fsSL https://bun.sh/install | bash",
        },
    ),
    ToolDefinition(
        id="npm",
        bin_names=("npm",),
        desc_en="Node.js package manager",
        desc_zh="Node.js 包管理器",
        install_hints={"Darwin": "brew install node", "Linux": "apt install npm"},
    ),
    ToolDefinition(
        id="cargo",
        bin_names=("cargo",),
        desc_en="Rust package manager and build tool",
        desc_zh="Rust 包管理器 and BuildTool",
        tags=frozenset({"json_output"}),
        install_hints={
            "Darwin": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh",
            "Linux": "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh",
        },
    ),
    ToolDefinition(
        id="go",
        bin_names=("go",),
        desc_en="Go runtime and build tool",
        desc_zh="Go 运行时 and BuildTool",
        install_hints={"Darwin": "brew install go", "Linux": "apt install golang"},
    ),
    ToolDefinition(
        id="make",
        bin_names=("make",),
        desc_en="Build automation tool",
        desc_zh="BuildAuto化Tool",
        install_hints={"Darwin": "xcode-select --install", "Linux": "apt install make"},
    ),
    # ── System / Files ───────────────────────────────────────
    ToolDefinition(
        id="tree",
        bin_names=("tree",),
        desc_en="Directory tree visualization",
        desc_zh="Directory树可视化",
        install_hints={"Darwin": "brew install tree", "Linux": "apt install tree", "Windows": "choco install tree"},
    ),
    ToolDefinition(
        id="zip",
        bin_names=("zip",),
        desc_en="Create ZIP archives",
        desc_zh="Create ZIP Compress包",
        install_hints={"Linux": "apt install zip"},
    ),
    ToolDefinition(
        id="unzip",
        bin_names=("unzip",),
        desc_en="Extract ZIP archives",
        desc_zh="Decompress ZIP Compress包",
        install_hints={"Linux": "apt install unzip"},
    ),
    ToolDefinition(
        id="tar",
        bin_names=("tar",),
        desc_en="Archive utility (tar, tar.gz, tar.bz2)",
        desc_zh="归档Tool（tar/gz/bz2）",
    ),
    # ── Document ─────────────────────────────────────────────
    ToolDefinition(
        id="pandoc",
        bin_names=("pandoc",),
        desc_en="Universal document converter (md, docx, pdf, html, ...)",
        desc_zh="万能文档Convert器（md/docx/pdf/html/…）",
        install_hints={
            "Darwin": "brew install pandoc",
            "Linux": "apt install pandoc",
            "Windows": "choco install pandoc",
        },
    ),
    # ── Remote ───────────────────────────────────────────────
    ToolDefinition(
        id="ssh",
        bin_names=("ssh",),
        desc_en="Secure remote shell access",
        desc_zh="SecurityRemote Shell 访问",
    ),
    ToolDefinition(
        id="rsync",
        bin_names=("rsync",),
        desc_en="Fast incremental file sync (local or remote)",
        desc_zh="fast增量FileSync（Local or Remote）",
        install_hints={"Darwin": "brew install rsync", "Linux": "apt install rsync"},
    ),
)
