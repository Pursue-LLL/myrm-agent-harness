"""Artifact type mappings — framework-agnostic constants.

Single Source of Truth for artifact type definitions, extension-to-language mappings,
and MIME type classifications. Usable by both agent/ and toolkits/.
"""

from enum import StrEnum
from pathlib import Path
from typing import TypedDict


class ArtifactType(StrEnum):
    """Artifact type enumeration."""

    CODE = "code"
    DOCUMENT = "document"
    HTML = "html"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    SVG = "svg"
    MERMAID = "mermaid"
    PDF = "pdf"
    BINARY = "binary"
    REACT = "react"


# ==================== Extension → Language Mapping ====================

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".groovy": "groovy",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".erb": "erb",
    ".php": "php",
    ".swift": "swift",
    ".m": "objectivec",
    ".mm": "objectivec",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "fish",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".json": "json",
    ".jsonc": "jsonc",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".toml": "toml",
    ".ini": "ini",
    ".conf": "ini",
    ".md": "markdown",
    ".mdx": "mdx",
    ".rst": "restructuredtext",
    ".tex": "latex",
    ".svg": "xml",
    ".mermaid": "mermaid",
    ".mmd": "mermaid",
    ".vue": "vue",
    ".svelte": "svelte",
    ".r": "r",
    ".R": "r",
    ".lua": "lua",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".hs": "haskell",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".fs": "fsharp",
    ".fsx": "fsharp",
    ".pl": "perl",
    ".pm": "perl",
    ".dockerfile": "dockerfile",
    ".dockerignore": "ignore",
    ".gitignore": "ignore",
    ".env": "dotenv",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
}


# ==================== Extension → Artifact Type Mapping ====================

EXTENSION_TO_ARTIFACT_TYPE: dict[str, ArtifactType] = {
    ".py": ArtifactType.CODE,
    ".js": ArtifactType.CODE,
    ".jsx": ArtifactType.CODE,
    ".ts": ArtifactType.CODE,
    ".tsx": ArtifactType.CODE,
    ".java": ArtifactType.CODE,
    ".c": ArtifactType.CODE,
    ".cpp": ArtifactType.CODE,
    ".h": ArtifactType.CODE,
    ".hpp": ArtifactType.CODE,
    ".go": ArtifactType.CODE,
    ".rs": ArtifactType.CODE,
    ".rb": ArtifactType.CODE,
    ".php": ArtifactType.CODE,
    ".swift": ArtifactType.CODE,
    ".kt": ArtifactType.CODE,
    ".scala": ArtifactType.CODE,
    ".cs": ArtifactType.CODE,
    ".sh": ArtifactType.CODE,
    ".bash": ArtifactType.CODE,
    ".sql": ArtifactType.CODE,
    ".json": ArtifactType.CODE,
    ".yaml": ArtifactType.CODE,
    ".yml": ArtifactType.CODE,
    ".xml": ArtifactType.CODE,
    ".toml": ArtifactType.CODE,
    ".css": ArtifactType.CODE,
    ".scss": ArtifactType.CODE,
    ".less": ArtifactType.CODE,
    ".vue": ArtifactType.CODE,
    ".svelte": ArtifactType.CODE,
    ".md": ArtifactType.DOCUMENT,
    ".mdx": ArtifactType.DOCUMENT,
    ".txt": ArtifactType.DOCUMENT,
    ".rst": ArtifactType.DOCUMENT,
    ".html": ArtifactType.HTML,
    ".htm": ArtifactType.HTML,
    ".svg": ArtifactType.SVG,
    ".mermaid": ArtifactType.MERMAID,
    ".mmd": ArtifactType.MERMAID,
    ".png": ArtifactType.IMAGE,
    ".jpg": ArtifactType.IMAGE,
    ".jpeg": ArtifactType.IMAGE,
    ".gif": ArtifactType.IMAGE,
    ".webp": ArtifactType.IMAGE,
    ".bmp": ArtifactType.IMAGE,
    ".ico": ArtifactType.IMAGE,
    ".mp3": ArtifactType.AUDIO,
    ".wav": ArtifactType.AUDIO,
    ".ogg": ArtifactType.AUDIO,
    ".flac": ArtifactType.AUDIO,
    ".m4a": ArtifactType.AUDIO,
    ".pdf": ArtifactType.PDF,
}

_EXTRA_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({".log", ".csv"})

_EXTRA_BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pptx",
        ".docx",
        ".xlsx",
        ".zip",
        ".tar",
        ".gz",
        ".rar",
        ".7z",
        ".exe",
        ".dmg",
        ".pkg",
        ".deb",
        ".rpm",
        ".apk",
        ".ipa",
        ".mp4",
        ".avi",
        ".mov",
        ".mkv",
    }
)


# ==================== MIME → Artifact Type Mapping ====================

MIME_TO_ARTIFACT_TYPE: dict[str, ArtifactType] = {
    "text/javascript": ArtifactType.CODE,
    "application/javascript": ArtifactType.CODE,
    "text/typescript": ArtifactType.CODE,
    "text/x-python": ArtifactType.CODE,
    "text/x-java": ArtifactType.CODE,
    "text/x-c": ArtifactType.CODE,
    "text/x-cpp": ArtifactType.CODE,
    "text/x-go": ArtifactType.CODE,
    "text/x-rust": ArtifactType.CODE,
    "application/json": ArtifactType.CODE,
    "text/yaml": ArtifactType.CODE,
    "text/x-yaml": ArtifactType.CODE,
    "application/xml": ArtifactType.CODE,
    "text/xml": ArtifactType.CODE,
    "text/css": ArtifactType.CODE,
    "text/plain": ArtifactType.DOCUMENT,
    "text/markdown": ArtifactType.DOCUMENT,
    "text/x-markdown": ArtifactType.DOCUMENT,
    "text/html": ArtifactType.HTML,
    "image/png": ArtifactType.IMAGE,
    "image/jpeg": ArtifactType.IMAGE,
    "image/gif": ArtifactType.IMAGE,
    "image/webp": ArtifactType.IMAGE,
    "image/bmp": ArtifactType.IMAGE,
    "image/x-icon": ArtifactType.IMAGE,
    "image/svg+xml": ArtifactType.SVG,
    "audio/mpeg": ArtifactType.AUDIO,
    "audio/wav": ArtifactType.AUDIO,
    "audio/ogg": ArtifactType.AUDIO,
    "audio/flac": ArtifactType.AUDIO,
    "audio/mp4": ArtifactType.AUDIO,
    "application/pdf": ArtifactType.PDF,
    "application/octet-stream": ArtifactType.BINARY,
}


# ==================== Security ====================

ACTIVE_CONTENT_MIME_TYPES: frozenset[str] = frozenset({"text/html", "application/xhtml+xml", "image/svg+xml"})


def is_active_content(mime_type: str) -> bool:
    """Check if MIME type is active content (XSS risk)."""
    return mime_type in ACTIVE_CONTENT_MIME_TYPES


def is_text_content(data: bytes, sample_size: int = 8192) -> bool:
    """Detect whether content is text by null-byte probing."""
    chunk = data[:sample_size]
    return b"\x00" not in chunk


# ==================== Utility Functions ====================


def infer_language_from_extension(filename: str) -> str | None:
    """Infer programming language from filename extension."""
    ext = Path(filename).suffix.lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


def infer_artifact_type_from_extension(filename: str) -> ArtifactType:
    """Infer artifact type from filename extension with fallback strategy."""
    ext = Path(filename).suffix.lower()
    if ext in EXTENSION_TO_ARTIFACT_TYPE:
        return EXTENSION_TO_ARTIFACT_TYPE[ext]
    if ext in _EXTRA_DOCUMENT_EXTENSIONS:
        return ArtifactType.DOCUMENT
    if ext in _EXTRA_BINARY_EXTENSIONS:
        return ArtifactType.BINARY
    return ArtifactType.BINARY


def infer_artifact_type_from_mime(mime_type: str) -> ArtifactType:
    """Infer artifact type from MIME type."""
    return MIME_TO_ARTIFACT_TYPE.get(mime_type, ArtifactType.BINARY)


# ==================== API Response Format ====================


class ArtifactMappings(TypedDict):
    """Return type for get_all_mappings."""

    artifactTypes: list[str]
    extensionToLanguage: dict[str, str]
    extensionToArtifactType: dict[str, str]
    mimeToArtifactType: dict[str, str]


def get_all_mappings() -> ArtifactMappings:
    """Get all mappings for API responses."""
    return ArtifactMappings(
        artifactTypes=[t.value for t in ArtifactType],
        extensionToLanguage=dict(EXTENSION_TO_LANGUAGE),
        extensionToArtifactType={k: v.value for k, v in EXTENSION_TO_ARTIFACT_TYPE.items()},
        mimeToArtifactType={k: v.value for k, v in MIME_TO_ARTIFACT_TYPE.items()},
    )
