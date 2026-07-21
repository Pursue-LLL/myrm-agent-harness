"""Filter file paths that belong to disabled skills.

Disabled skill roots are passed from the business layer via RunnableConfig context
(``disabled_skill_roots``). glob/grep/file_read use this to avoid surfacing files
under skills the user has turned off.

[OUTPUT]
- normalize_path: normalize a path for prefix comparison
- is_under_disabled_skill_root: check whether a path is under a disabled root
- filter_disabled_skill_paths: drop paths under disabled skill roots
- get_disabled_skill_roots: read roots from RunnableConfig context
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.context_management.context import extract_context_from_runnable_config


def normalize_path(path: str) -> str:
    return os.path.normpath(path)


def is_under_disabled_skill_root(path: str, disabled_roots: Sequence[str]) -> bool:
    if not disabled_roots:
        return False
    norm = normalize_path(path)
    for root in disabled_roots:
        root_norm = normalize_path(root)
        if norm == root_norm or norm.startswith(root_norm + os.sep):
            return True
    return False


def filter_disabled_skill_paths(paths: Sequence[str], disabled_roots: Sequence[str]) -> list[str]:
    if not disabled_roots:
        return list(paths)
    return [p for p in paths if not is_under_disabled_skill_root(p, disabled_roots)]


def get_disabled_skill_roots(config: RunnableConfig | None) -> list[str]:
    ctx = extract_context_from_runnable_config(config)
    raw = ctx.get("disabled_skill_roots")
    if not isinstance(raw, list):
        return []
    roots: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            roots.append(item.strip())
    return roots
