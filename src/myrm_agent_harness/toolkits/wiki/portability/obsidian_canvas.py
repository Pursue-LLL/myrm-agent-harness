"""Obsidian vault structure, canvas text extraction, and 1-hop link parsing.

[INPUT]
- pathlib::Path (POS: filesystem path operations)
- json (POS: JSON Canvas spec parsing)
- ..core.link_extraction::find_wikilinks (POS: link syntax SSOT; code is never a link)

[OUTPUT]
- extract_canvas_text_nodes: Extracts clean text nodes and labels from .canvas files.
- extract_wikilinks_from_markdown: Extracts [[target|alias]] references from Markdown text.
- resolve_one_hop_wikilinks: Resolves 1-hop neighbor notes given a seed note and vault root.

[POS]
Harness-level pure file-format utilities for Obsidian interoperability.
Decoupled from database, network, and multi-tenant logic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.link_extraction import find_wikilinks

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CanvasTextNode:
    """A textual node extracted from an Obsidian .canvas file."""

    node_id: str
    node_type: str  # "text", "file", "link", "group"
    content: str
    label: str = ""


@dataclass(frozen=True, slots=True)
class WikilinkReference:
    """A parsed wikilink reference."""

    target: str
    alias: str = ""
    raw_match: str = ""


def extract_canvas_text_nodes(canvas_path: Path | str) -> list[CanvasTextNode]:
    """Parse an Obsidian .canvas JSON file and extract textual node content.

    Complies with JSON Canvas 1.0 spec:
    - nodes[type="text"]: Extracts node.text
    - nodes[type="file"]: Extracts node.file and optional node.label
    - nodes[type="link"]: Extracts node.url and optional node.label
    - nodes[type="group"]: Extracts node.label (section titles)
    """
    path = Path(canvas_path)
    if not path.is_file():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.debug("Failed to read or parse canvas file %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        return []

    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        return []

    extracted: list[CanvasTextNode] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue

        node_id = str(node.get("id", ""))
        node_type = str(node.get("type", ""))
        text = str(node.get("text", "")).strip()
        label = str(node.get("label", "")).strip()

        if node_type == "text" and text:
            extracted.append(
                CanvasTextNode(
                    node_id=node_id,
                    node_type="text",
                    content=text,
                    label=label,
                )
            )
        elif node_type == "file":
            file_ref = str(node.get("file", "")).strip()
            if file_ref or label:
                extracted.append(
                    CanvasTextNode(
                        node_id=node_id,
                        node_type="file",
                        content=file_ref,
                        label=label,
                    )
                )
        elif node_type == "link":
            url = str(node.get("url", "")).strip()
            if url or label:
                extracted.append(
                    CanvasTextNode(
                        node_id=node_id,
                        node_type="link",
                        content=url,
                        label=label,
                    )
                )
        elif node_type == "group" and label:
            extracted.append(
                CanvasTextNode(
                    node_id=node_id,
                    node_type="group",
                    content=label,
                    label=label,
                )
            )

    return extracted


def extract_wikilinks_from_markdown(content: str) -> list[WikilinkReference]:
    """Extract all [[Target|Alias]] wikilinks from Markdown text."""
    return [
        WikilinkReference(target=parts.note, alias=(parts.label or "").strip(), raw_match=raw)
        for raw, parts in find_wikilinks(content)
    ]


def resolve_one_hop_wikilinks(
    seed_markdown_path: Path | str,
    vault_root: Path | str,
    *,
    case_insensitive: bool = True,
) -> dict[str, Path]:
    """Resolve 1-hop neighbor file paths referenced by a seed markdown file.

    Returns a mapping of target name -> resolved absolute Path in the vault.
    """
    seed_path = Path(seed_markdown_path)
    root = Path(vault_root)

    if not seed_path.is_file() or not root.is_dir():
        return {}

    try:
        content = seed_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return {}

    links = extract_wikilinks_from_markdown(content)
    if not links:
        return {}

    # Build a lookup index of vault markdown files
    # Case-insensitive stem/name -> Path
    index: dict[str, Path] = {}
    for md_file in root.rglob("*.md"):
        if md_file.is_file():
            key = md_file.stem.lower() if case_insensitive else md_file.stem
            if key not in index:
                index[key] = md_file

    resolved: dict[str, Path] = {}
    for ref in links:
        target_stem = Path(ref.target).stem
        lookup_key = target_stem.lower() if case_insensitive else target_stem
        if lookup_key in index:
            resolved[ref.target] = index[lookup_key]

    return resolved
