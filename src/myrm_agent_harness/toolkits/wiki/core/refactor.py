"""Wiki link refactoring and alias injection engine.

[INPUT]
- pathlib::Path (POS: standard library file path operations)
- re (POS: regular expressions)
- frontmatter_contract.load_frontmatter_metadata (POS: frontmatter parsing)
- frontmatter_contract.serialize_frontmatter_block (POS: frontmatter serialization)

[OUTPUT]
- LinkRefactorEngine: Engine to update markdown links, Obsidian wikilinks, and aliases when files move/rename.

[POS]
Maintains relative links, Obsidian [[wikilinks]], and frontmatter aliases across wiki move/rename events.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    load_frontmatter_metadata,
    serialize_frontmatter_block,
)

logger = logging.getLogger(__name__)

_CODE_FENCE_OR_INLINE_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")


def _concept_slug_from_path(concepts_dir: Path, path: Path) -> str:
    """Derive relative concept slug without .md suffix."""
    try:
        rel = path.relative_to(concepts_dir)
        return str(rel.with_suffix("")).replace("\\", "/")
    except ValueError:
        return str(path.with_suffix("")).replace("\\", "/")


def _inject_alias_to_moved_file(target_file: Path, old_concept_slug: str) -> bool:
    """Inject old concept path into aliases if not already present."""
    if not target_file.is_file():
        return False
    try:
        content = target_file.read_text(encoding="utf-8")
        metadata, body = load_frontmatter_metadata(content)
        raw_aliases = metadata.get("aliases")
        current_aliases: list[str] = []
        if isinstance(raw_aliases, list):
            current_aliases = [str(item).strip() for item in raw_aliases if str(item).strip()]
        elif isinstance(raw_aliases, str) and raw_aliases.strip():
            current_aliases = [raw_aliases.strip()]

        normalized_existing = {a.casefold() for a in current_aliases}
        candidate = old_concept_slug.strip()
        if candidate and candidate.casefold() not in normalized_existing:
            current_aliases.append(candidate)
            metadata["aliases"] = current_aliases
            new_content = serialize_frontmatter_block(metadata) + body.lstrip("\n")
            target_file.write_text(new_content, encoding="utf-8")
            return True
    except Exception as exc:
        logger.warning("Failed to inject alias to %s: %s", target_file, exc)
    return False


class LinkRefactorEngine:
    """Engine to update markdown links, Obsidian wikilinks, and aliases when files move or rename."""

    def __init__(self, concepts_dir: Path) -> None:
        self.concepts_dir = concepts_dir

    def refactor_links(
        self,
        old_path: Path,
        new_path: Path,
        *,
        preserve_alias: bool = True,
    ) -> int:
        """Scan markdown files in concepts_dir, updating links and injecting aliases.

        Args:
            old_path: The previous absolute path of the file/folder.
            new_path: The new absolute path of the file/folder.
            preserve_alias: Whether to append the old concept path to new_path aliases.

        Returns:
            Number of referencing files updated.
        """
        if not self.concepts_dir.exists():
            return 0

        # 1. Inject alias to moved file(s) for canonical backward-compatibility
        if preserve_alias:
            if new_path.is_file():
                old_slug = _concept_slug_from_path(self.concepts_dir, old_path)
                _inject_alias_to_moved_file(new_path, old_slug)
            elif new_path.is_dir():
                for md_file in new_path.rglob("*.md"):
                    rel_to_new = md_file.relative_to(new_path)
                    old_corresponding = old_path / rel_to_new
                    old_slug = _concept_slug_from_path(self.concepts_dir, old_corresponding)
                    _inject_alias_to_moved_file(md_file, old_slug)

        # 2. Refactor incoming links from other markdown files
        updated_files_count = 0
        is_dir = old_path.is_dir() or new_path.is_dir()

        for md_file in self.concepts_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                new_content = self._update_content_links(content, md_file, old_path, new_path, is_dir)

                if content != new_content:
                    md_file.write_text(new_content, encoding="utf-8")
                    updated_files_count += 1
            except Exception as exc:
                logger.warning("Failed to refactor links in %s: %s", md_file, exc)

        return updated_files_count

    def _update_content_links(
        self,
        content: str,
        current_file: Path,
        old_target: Path,
        new_target: Path,
        is_dir: bool,
    ) -> str:
        """Update markdown links and Obsidian wikilinks in content, preserving code blocks."""
        # Mask code blocks from regex substitution
        fences: list[str] = []

        def _save_fence(match: re.Match[str]) -> str:
            fences.append(match.group(0))
            return f"\x00CODE_{len(fences) - 1}\x00"

        masked = _CODE_FENCE_OR_INLINE_RE.sub(_save_fence, content)

        # 1. Update Markdown [text](url) links
        def _replace_markdown_link(match: re.Match[str]) -> str:
            text = match.group(1)
            url = match.group(2)
            if url.startswith(("http://", "https://", "#", "mailto:")):
                return match.group(0)

            try:
                link_path = (current_file.parent / url).resolve()
                needs_update = False
                if is_dir:
                    if old_target in link_path.parents or link_path == old_target:
                        needs_update = True
                else:
                    if link_path == old_target:
                        needs_update = True

                if needs_update:
                    if is_dir:
                        rel_to_old = link_path.relative_to(old_target)
                        new_abs_path = new_target / rel_to_old
                    else:
                        new_abs_path = new_target

                    new_rel_path = os.path.relpath(new_abs_path, current_file.parent).replace("\\", "/")
                    return f"[{text}]({new_rel_path})"
            except Exception:
                pass
            return match.group(0)

        masked = _MARKDOWN_LINK_RE.sub(_replace_markdown_link, masked)

        # 2. Update Obsidian [[wikilink]] targets
        old_slug = _concept_slug_from_path(self.concepts_dir, old_target)
        new_slug = _concept_slug_from_path(self.concepts_dir, new_target)
        old_stem = old_target.stem

        def _replace_wikilink(match: re.Match[str]) -> str:
            inner = match.group(1)
            label_part: str | None = None
            if "|" in inner:
                target_part, label_part = inner.split("|", 1)
            else:
                target_part = inner

            fragment_part: str | None = None
            if "#" in target_part:
                note_part, fragment_part = target_part.split("#", 1)
            else:
                note_part = target_part

            clean_note = note_part.strip()
            has_md_suffix = clean_note.lower().endswith(".md")
            if has_md_suffix:
                clean_note = clean_note[:-3]

            new_note_part: str | None = None
            if not is_dir:
                if clean_note.casefold() in {old_slug.casefold(), old_stem.casefold()}:
                    new_note_part = new_slug if not has_md_suffix else f"{new_slug}.md"
            else:
                if clean_note.casefold() == old_slug.casefold():
                    new_note_part = new_slug if not has_md_suffix else f"{new_slug}.md"
                elif clean_note.casefold().startswith(f"{old_slug.casefold()}/"):
                    sub_suffix = clean_note[len(old_slug) + 1 :]
                    new_note_part = f"{new_slug}/{sub_suffix}" if not has_md_suffix else f"{new_slug}/{sub_suffix}.md"

            if new_note_part is None:
                return match.group(0)

            result_target = new_note_part
            if fragment_part is not None:
                result_target = f"{result_target}#{fragment_part}"
            if label_part is not None:
                return f"[[{result_target}|{label_part}]]"
            return f"[[{result_target}]]"

        masked = _WIKILINK_RE.sub(_replace_wikilink, masked)

        # Restore masked code blocks
        def _restore_fence(match: re.Match[str]) -> str:
            idx = int(match.group(1))
            return fences[idx]

        return re.sub(r"\x00CODE_(\d+)\x00", _restore_fence, masked)

