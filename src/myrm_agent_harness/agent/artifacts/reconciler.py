"""Physical disk artifact reconciliation and verification engine.

Extracts generated deliverable file paths from tool outputs and verifies their
actual existence on the physical filesystem (or within a workspace root).
Automatically registers verified artifacts into the active ArtifactRegistry.

[INPUT]
- Tool result string / data dict
- Optional workspace_root directory

[OUTPUT]
- extract_physical_artifacts(): pure extractor returning verified existing paths
- reconcile_and_register_artifacts(): extracts, validates, and registers into ArtifactRegistry

[POS]
Harness artifact lifecycle engine; bridges arbitrary tool outputs (Bash, Python scripts,
custom tools) to verified physical deliverable artifacts on disk.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .filters import should_ignore_artifact

if TYPE_CHECKING:
    from .registry import ArtifactRegistry

logger = logging.getLogger(__name__)

# Standard deliverable file extensions
_DELIVERABLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pptx",
        ".docx",
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".mp4",
        ".mp3",
        ".wav",
        ".txt",
        ".xlsx",
        ".xls",
        ".csv",
        ".json",
        ".html",
        ".md",
        ".zip",
        ".tar.gz",
        ".py",
        ".ts",
        ".tsx",
        ".js",
    }
)

_PREFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:已生成|已保存|保存至|保存到|存放于|输出到|输出至|生成成功|路径|Saved to|Written to|Exported to|Output to)[^：:]*[:：]\s*(\S+)", re.IGNORECASE),
)

_STRIP_CHARS = "`'\"“”‘’，。；、,;:()[]{}<>"


def _clean_token(token: str) -> str:
    """Strip bounding markdown, quotes, and punctuation from extracted path candidate."""
    cleaned = token.strip()
    while cleaned and cleaned[0] in _STRIP_CHARS:
        cleaned = cleaned[1:]
    while cleaned and cleaned and cleaned[-1] in _STRIP_CHARS:
        cleaned = cleaned[:-1]
    return cleaned.strip()


def _is_valid_extension(path_str: str) -> bool:
    """Check if the filename has a known deliverable file extension."""
    lower_path = path_str.lower()
    return any(lower_path.endswith(ext) for ext in _DELIVERABLE_EXTENSIONS)


def _resolve_physical_file(candidate: str, workspace_root: str | None = None) -> str | None:
    """Verify if the candidate path exists on physical disk (absolute or workspace-relative)."""
    cleaned = _clean_token(candidate)
    if not cleaned or should_ignore_artifact(Path(cleaned).name):
        return None

    if not _is_valid_extension(cleaned):
        return None

    # 1. Test direct absolute or CWD-relative path
    try:
        if os.path.isfile(cleaned):
            return str(Path(cleaned).resolve())
    except (OSError, ValueError):
        pass

    # 2. Test relative to workspace_root if provided
    if workspace_root:
        try:
            ws_path = (Path(workspace_root) / cleaned).resolve()
            if ws_path.is_file():
                return str(ws_path)
        except (OSError, ValueError):
            pass

    return None


def extract_physical_artifacts(text_or_data: Any, workspace_root: str | None = None) -> list[str]:
    """Extract all existing physical deliverable file paths from tool result text or structure.

    Uses dual-path extraction:
      ① Regex capture with common Chinese/English generation prefixes;
      ② Tokenized scanning for valid extensions + physical file existence check.
    Returns deduplicated list of resolved absolute file paths in order of appearance.
    """
    if not text_or_data:
        return []

    found: list[str] = []
    seen: set[str] = set()

    def _accept(p_str: str) -> None:
        resolved = _resolve_physical_file(p_str, workspace_root=workspace_root)
        if resolved and resolved not in seen:
            seen.add(resolved)
            found.append(resolved)

    # If data is structured dict/json
    if isinstance(text_or_data, dict):
        for key in ("path", "file_path", "output_path", "output_file", "artifacts", "files"):
            val = text_or_data.get(key)
            if isinstance(val, str):
                _accept(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        _accept(item)
        text_content = json.dumps(text_or_data, ensure_ascii=False)
    else:
        text_content = str(text_or_data)

    if not text_content.strip():
        return found

    # Path 1: Prefix regex matching
    for pattern in _PREFIX_PATTERNS:
        for m in pattern.finditer(text_content):
            _accept(m.group(1))

    # Path 2: Tokenized delimiter splitting
    tokens = re.split(r"[\s，。；、,;：\n\r\t]+", text_content)
    for tok in tokens:
        if any(tok.lower().endswith(ext) for ext in _DELIVERABLE_EXTENSIONS):
            _accept(tok)

    return found


def reconcile_and_register_artifacts(
    text_or_data: Any,
    workspace_root: str | None = None,
    container_id: str | None = None,
    registry: ArtifactRegistry | None = None,
) -> list[str]:
    """Extract physically verified artifacts and register them into the ArtifactRegistry."""
    verified_paths = extract_physical_artifacts(text_or_data, workspace_root=workspace_root)
    if not verified_paths:
        return []

    from .registry import get_artifact_registry

    target_registry = registry or get_artifact_registry()
    if target_registry is not None:
        target_registry.add_files(verified_paths, container_id=container_id)
        logger.info("[ArtifactDiskReconciler] Registered %d verified artifacts on disk", len(verified_paths))

    return verified_paths


__all__ = [
    "extract_physical_artifacts",
    "reconcile_and_register_artifacts",
]
