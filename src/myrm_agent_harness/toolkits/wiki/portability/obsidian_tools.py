"""Obsidian Vault agent integration tools.

[INPUT]
- langchain_core.tools::tool
- myrm_agent_harness.toolkits.wiki.portability.obsidian_canvas::(
    extract_canvas_text_nodes,
    extract_wikilinks_from_markdown,
    resolve_one_hop_wikilinks,
  )

[OUTPUT]
- create_obsidian_tools: Factory producing obsidian_vault_search, obsidian_vault_read, and obsidian_inbox_write.

[POS]
Agent-facing tools for seamless interaction with local/bound Obsidian vaults.
Supports reading canvas text nodes, 1-hop [[Wikilink]] expansion, and safe approval-gated inbox writes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from myrm_agent_harness.toolkits.wiki.portability.obsidian_canvas import (
    extract_canvas_text_nodes,
    extract_wikilinks_from_markdown,
    resolve_one_hop_wikilinks,
)

logger = logging.getLogger(__name__)


def create_obsidian_tools(
    vault_path_provider: Callable[[], str | None],
    *,
    inbox_folder_name: str = "_Myrm_Inbox",
    approval_requester: Callable[[dict[str, object]], str | None] | None = None,
) -> list[object]:
    """Create LangChain tools for searching, reading, and inbox-writing to a bound Obsidian Vault."""

    @tool
    def obsidian_vault_search(
        query: Annotated[str, "Keywords or phrase to search within the Obsidian vault"],
        max_results: Annotated[int, "Maximum number of file matches to return (default: 5)"] = 5,
    ) -> str:
        """Search notes and canvas boards inside the bound Obsidian vault by keywords."""
        root_str = vault_path_provider()
        if not root_str:
            return "No Obsidian vault currently bound. Please bind a vault in settings or specify a path."

        root = Path(root_str)
        if not root.is_dir():
            return f"Bound Obsidian vault path does not exist: {root_str}"

        q_lower = query.lower()
        matches: list[tuple[str, str]] = []

        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part.startswith(".") for part in p.relative_to(root).parts):
                continue

            rel_str = p.relative_to(root).as_posix()
            stem_lower = p.stem.lower()

            # Fast match on filename
            if q_lower in stem_lower:
                matches.append((rel_str, f"[Filename Match] {rel_str}"))
                if len(matches) >= max_results:
                    break
                continue

            # Check content
            if p.suffix.lower() == ".md":
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore")
                    if q_lower in content.lower():
                        matches.append((rel_str, f"[Markdown Content Match] {rel_str}"))
                        if len(matches) >= max_results:
                            break
                except OSError:
                    continue
            elif p.suffix.lower() == ".canvas":
                nodes = extract_canvas_text_nodes(p)
                for node in nodes:
                    if q_lower in node.content.lower() or q_lower in node.label.lower():
                        matches.append(
                            (rel_str, f"[Canvas Match] {rel_str} (node: {node.label or node.content[:30]})")
                        )
                        if len(matches) >= max_results:
                            break
                        break

        if not matches:
            return f"No matches found for query '{query}' in Obsidian vault."

        output = [f"Found {len(matches)} matches in Obsidian vault:"]
        for _, desc in matches:
            output.append(f"- {desc}")
        return "\n".join(output)

    @tool
    def obsidian_vault_read(
        relative_path: Annotated[str, "Relative path of the note or canvas within the vault"],
        expand_wikilinks: Annotated[
            bool, "Whether to include 1-hop linked neighbor note summaries (default: True)"
        ] = True,
    ) -> str:
        """Read full content of an Obsidian note (.md) or canvas (.canvas), with optional 1-hop [[Wikilink]] expansion."""
        root_str = vault_path_provider()
        if not root_str:
            return "No Obsidian vault currently bound."

        root = Path(root_str)
        target = root / relative_path.strip("/\\")
        if not target.is_file():
            # Try appending .md if omitted
            if (root / f"{relative_path.strip('/\\')}.md").is_file():
                target = root / f"{relative_path.strip('/\\')}.md"
            else:
                return f"File '{relative_path}' not found in Obsidian vault."

        if target.suffix.lower() == ".canvas":
            nodes = extract_canvas_text_nodes(target)
            lines = [f"# Canvas: {target.name}\n"]
            for n in nodes:
                if n.node_type == "group":
                    lines.append(f"## Group: {n.label}")
                elif n.node_type == "text":
                    lines.append(f"- [Text] {n.content}")
                elif n.node_type == "file":
                    lines.append(f"- [File Card] {n.label or n.content}")
                elif n.node_type == "link":
                    lines.append(f"- [Link Card] {n.label or n.content}")
            return "\n".join(lines)

        try:
            content = target.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return f"Failed to read file: {exc}"

        output = [content]

        if expand_wikilinks and target.suffix.lower() == ".md":
            neighbors = resolve_one_hop_wikilinks(target, root)
            if neighbors:
                output.append("\n\n---\n### 1-Hop Wikilink Neighbors Context")
                for link_name, path in list(neighbors.items())[:5]:  # limit to top 5
                    try:
                        neighbor_text = path.read_text(encoding="utf-8", errors="ignore")
                        snippet = neighbor_text.strip()[:300].replace("\n", " ")
                        output.append(f"- **[[{link_name}]]** ({path.name}): {snippet}...")
                    except OSError:
                        continue

        return "\n".join(output)

    @tool
    def obsidian_inbox_write(
        title: Annotated[str, "Title or filename of the note to create in the Obsidian Inbox"],
        content: Annotated[str, "Markdown content of the note"],
        subfolder: Annotated[str, "Optional subfolder inside the Inbox"] = "",
    ) -> str:
        """Submit a markdown note to the Obsidian Vault's designated Inbox.

        NOTE: This operation triggers a human-in-the-loop approval request to protect
        user files from unintended modifications.
        """
        root_str = vault_path_provider()
        if not root_str:
            return "Cannot write note: No Obsidian vault currently bound."

        payload = {
            "title": title,
            "content": content,
            "subfolder": subfolder,
            "target_vault": root_str,
            "inbox_folder": inbox_folder_name,
        }

        if approval_requester:
            approval_id = approval_requester(payload)
            return (
                f"Note proposal for '{title}' submitted for user review (approval_id: {approval_id}). "
                f"It will be written to {inbox_folder_name}/{title}.md once approved."
            )

        return (
            f"Note proposal for '{title}' prepared for Inbox {inbox_folder_name}. "
            "Approval handler not configured; note held."
        )

    return [obsidian_vault_search, obsidian_vault_read, obsidian_inbox_write]
