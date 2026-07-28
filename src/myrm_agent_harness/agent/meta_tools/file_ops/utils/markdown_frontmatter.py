"""Markdown YAML frontmatter helpers for vault write fidelity.

[INPUT]
- Raw markdown note content (pre/post edit)

[OUTPUT]
- parse_frontmatter: metadata dict + body
- has_frontmatter_block / extract_frontmatter_block
- preserve_frontmatter_on_edit: reinject FM when LLM drops the block

[POS]
Generic markdown FM utilities shared by vault write guard and server wiki import.
"""

from __future__ import annotations

import re

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def has_frontmatter_block(content: str) -> bool:
    """Return True when content starts with a YAML frontmatter block."""
    return _FRONTMATTER_RE.match(content) is not None


def extract_frontmatter_block(content: str) -> str | None:
    """Return the full frontmatter region including trailing newline, if present."""
    match = _FRONTMATTER_RE.match(content)
    if match is None:
        return None
    return content[: match.end()]


def parse_frontmatter(content: str) -> tuple[dict[str, object], str]:
    """Extract YAML frontmatter from Markdown content.

    Returns (metadata_dict, body_without_frontmatter).
    Supports inline arrays and YAML indented lists common in Obsidian notes.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    raw_fm = match.group(1)
    body = content[match.end() :]
    metadata: dict[str, object] = {}
    current_list_key: str | None = None
    current_list: list[str] = []

    def _flush_list() -> None:
        nonlocal current_list_key, current_list
        if current_list_key and current_list:
            metadata[current_list_key] = current_list
        current_list_key = None
        current_list = []

    for raw_line in raw_fm.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- ") and current_list_key is not None:
            current_list.append(stripped[2:].strip().strip("'\""))
            continue

        _flush_list()

        if ":" not in stripped:
            continue

        key, _, value = stripped.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if not value:
            current_list_key = key
            current_list = []
        elif value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            metadata[key] = items
        elif value.startswith("'") or value.startswith('"'):
            metadata[key] = value.strip("'\"")
        else:
            metadata[key] = value

    _flush_list()
    return metadata, body


def preserve_frontmatter_on_edit(pre_content: str, post_content: str) -> tuple[str, list[str]]:
    """Reinject pre-edit frontmatter when the post-edit content dropped it."""
    warnings: list[str] = []
    if not has_frontmatter_block(pre_content):
        return post_content, warnings
    if has_frontmatter_block(post_content):
        return post_content, warnings

    fm_block = extract_frontmatter_block(pre_content)
    if fm_block is None:
        return post_content, warnings

    merged = f"{fm_block}{post_content.lstrip('\n')}"
    warnings.append("Preserved YAML frontmatter from the pre-edit note.")
    return merged, warnings
