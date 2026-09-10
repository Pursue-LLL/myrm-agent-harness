"""Wiki link refactoring and alias injection engine.

[INPUT]
- pathlib::Path (POS: standard library file path operations)
- re (POS: regular expressions)
- frontmatter_contract.load_frontmatter_metadata (POS: frontmatter parsing)
- frontmatter_contract.serialize_frontmatter_block (POS: frontmatter serialization)
- canonical_registry.CANONICAL_ID_KEY (POS: canonical identity key)
- canonical_registry.derive_canonical_id (POS: stable slug to canonical id generator)

[OUTPUT]
- RefactorReport: Report containing updated file count and modified concept slugs.
- LinkRefactorEngine: Engine to update markdown links, Obsidian wikilinks, and aliases when files move/rename.

[POS]
Maintains relative links, Obsidian [[wikilinks]], canonical identity, and frontmatter aliases across wiki move/rename events.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.canonical_registry import (
    CANONICAL_ID_KEY,
    derive_canonical_id,
)
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    load_frontmatter_metadata,
    serialize_frontmatter_block,
)

logger = logging.getLogger(__name__)

_CODE_FENCE_OR_INLINE_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")


@dataclass(frozen=True, slots=True)
class RefactorReport:
    """Report of wiki link refactoring operations.

    Implements integer protocol methods (__int__, __index__, __eq__) for backwards
    compatibility with call sites expecting an integer updated count.
    """

    updated_count: int
    modified_concept_paths: tuple[str, ...] = ()

    def __int__(self) -> int:
        return self.updated_count

    def __index__(self) -> int:
        return self.updated_count

    def __str__(self) -> str:
        return str(self.updated_count)

    def __bool__(self) -> bool:
        return self.updated_count > 0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.updated_count == other
        if isinstance(other, RefactorReport):
            return (
                self.updated_count == other.updated_count
                and self.modified_concept_paths == other.modified_concept_paths
            )
        return False


def _concept_slug_from_path(concepts_dir: Path, path: Path) -> str:
    """Derive relative concept slug without .md suffix."""
    try:
        rel = path.relative_to(concepts_dir)
        return str(rel.with_suffix("")).replace("\\", "/")
    except ValueError:
        return str(path.with_suffix("")).replace("\\", "/")


def _inject_rename_metadata(target_file: Path, old_concept_slug: str) -> bool:
    """Inject canonical id, supersedes, and aliases to moved/renamed concept file."""
    if not target_file.is_file():
        return False
    try:
        content = target_file.read_text(encoding="utf-8")
        metadata, body = load_frontmatter_metadata(content)

        changed = False
        old_slug_clean = old_concept_slug.strip()

        # 1. Canonical ID pinning: if missing, lock to old slug's derived canonical id
        existing_canonical = metadata.get(CANONICAL_ID_KEY)
        if not existing_canonical or not str(existing_canonical).strip():
            metadata[CANONICAL_ID_KEY] = derive_canonical_id(old_concept_slug)
            changed = True

        # 2. Supersedes tracking: record superseded concept slug
        raw_supersedes = metadata.get("supersedes")
        current_supersedes: list[str] = []
        if isinstance(raw_supersedes, list):
            current_supersedes = [str(item).strip() for item in raw_supersedes if str(item).strip()]
        elif isinstance(raw_supersedes, str) and raw_supersedes.strip():
            current_supersedes = [raw_supersedes.strip()]

        if old_slug_clean and old_slug_clean not in current_supersedes:
            current_supersedes.append(old_slug_clean)
            metadata["supersedes"] = current_supersedes
            changed = True

        # 3. Aliases tracking: add old concept slug to aliases
        raw_aliases = metadata.get("aliases")
        current_aliases: list[str] = []
        if isinstance(raw_aliases, list):
            current_aliases = [str(item).strip() for item in raw_aliases if str(item).strip()]
        elif isinstance(raw_aliases, str) and raw_aliases.strip():
            current_aliases = [raw_aliases.strip()]

        normalized_existing = {a.casefold() for a in current_aliases}
        if old_slug_clean and old_slug_clean.casefold() not in normalized_existing:
            current_aliases.append(old_slug_clean)
            metadata["aliases"] = current_aliases
            changed = True

        if changed:
            new_content = serialize_frontmatter_block(metadata) + body.lstrip("\n")
            target_file.write_text(new_content, encoding="utf-8")
            return True
    except Exception as exc:
        logger.warning("Failed to inject rename metadata to %s: %s", target_file, exc)
    return False


# Compatibility alias
_inject_alias_to_moved_file = _inject_rename_metadata


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
    ) -> RefactorReport:
        """Scan markdown files in concepts_dir, updating links and injecting aliases.

        Args:
            old_path: The previous absolute path of the file/folder.
            new_path: The new absolute path of the file/folder.
            preserve_alias: Whether to append the old concept path to new_path aliases.

        Returns:
            RefactorReport with updated files count and modified concept slugs.
        """
        if not self.concepts_dir.exists():
            return RefactorReport(updated_count=0, modified_concept_paths=())

        # 1. Inject alias and canonical metadata to moved file(s) for canonical backward-compatibility
        if preserve_alias:
            if new_path.is_file():
                old_slug = _concept_slug_from_path(self.concepts_dir, old_path)
                _inject_rename_metadata(new_path, old_slug)
            elif new_path.is_dir():
                for md_file in new_path.rglob("*.md"):
                    rel_to_new = md_file.relative_to(new_path)
                    old_corresponding = old_path / rel_to_new
                    old_slug = _concept_slug_from_path(self.concepts_dir, old_corresponding)
                    _inject_rename_metadata(md_file, old_slug)

        # 2. Refactor incoming links from other markdown files
        updated_slugs: list[str] = []
        is_dir = old_path.is_dir() or new_path.is_dir()

        # Pre-compute case-folded global stem collision check once for O(1) disambiguation
        has_stem_conflict = False
        if not is_dir:
            old_stem_cf = old_path.stem.casefold()
            old_resolved = old_path.resolve()
            new_resolved = new_path.resolve()
            has_stem_conflict = any(
                p.stem.casefold() == old_stem_cf
                and p.resolve() != old_resolved
                and p.resolve() != new_resolved
                for p in self.concepts_dir.rglob("*.md")
            )

        for md_file in self.concepts_dir.rglob("*.md"):
            # Avoid refactoring within the moved files themselves if they were already moved
            if md_file == new_path or (new_path.is_dir() and new_path in md_file.parents):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                new_content = self._update_content_links(
                    content, md_file, old_path, new_path, is_dir, has_stem_conflict=has_stem_conflict
                )

                if content != new_content:
                    md_file.write_text(new_content, encoding="utf-8")
                    concept_slug = _concept_slug_from_path(self.concepts_dir, md_file)
                    updated_slugs.append(concept_slug)
            except Exception as exc:
                logger.warning("Failed to refactor links in %s: %s", md_file, exc)

        return RefactorReport(
            updated_count=len(updated_slugs),
            modified_concept_paths=tuple(updated_slugs),
        )

    def _is_short_link_target(
        self,
        current_file: Path,
        clean_note: str,
        old_target: Path,
        *,
        has_stem_conflict: bool = False,
    ) -> bool:
        """Disambiguate short [[stem]] wikilink to check if it points to old_target.

        Fully case-insensitive across platforms (macOS / Linux ext4) and O(1) evaluation.
        """
        clean_note_cf = clean_note.casefold()
        old_target_res = old_target.resolve()

        # 1. If current_file has a sibling matching the stem and sibling != old_target,
        # Obsidian scoping rules resolve [[stem]] to sibling, not old_target.
        try:
            for p in current_file.parent.iterdir():
                if (
                    p.is_file()
                    and p.suffix.lower() == ".md"
                    and p.stem.casefold() == clean_note_cf
                    and p.resolve() != old_target_res
                ):
                    return False
        except OSError:
            pass

        # 2. If old_target was in the same folder as current_file, it was the target.
        if old_target.parent.resolve() == current_file.parent.resolve():
            return True

        # 3. If in a different folder, check pre-computed global collision in vault.
        return not has_stem_conflict


    def _update_content_links(
        self,
        content: str,
        current_file: Path,
        old_target: Path,
        new_target: Path,
        is_dir: bool,
        *,
        has_stem_conflict: bool = False,
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

            url_path_part, _, fragment = url.partition("#")
            try:
                link_path = (current_file.parent / url_path_part).resolve()
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
                    if fragment:
                        new_rel_path = f"{new_rel_path}#{fragment}"
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
                if clean_note.casefold() == old_slug.casefold():
                    new_note_part = new_slug if not has_md_suffix else f"{new_slug}.md"

                elif (
                    clean_note.casefold() == old_stem.casefold()
                    and "/" not in clean_note
                    and self._is_short_link_target(
                        current_file, clean_note, old_target, has_stem_conflict=has_stem_conflict
                    )
                ):
                    if new_target.parent.resolve() == current_file.parent.resolve():
                        new_note_part = new_target.stem if not has_md_suffix else f"{new_target.stem}.md"
                    else:
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


