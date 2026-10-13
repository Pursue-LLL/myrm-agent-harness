"""Wiki link refactoring and alias injection engine.

[INPUT]
- pathlib::Path (POS: standard library file path operations)
- re (POS: regular expressions)
- link_extraction.MARKDOWN_LINK_RE, WIKILINK_RE, parse_wikilink, protect_code, is_external_link (POS: link syntax SSOT; code is never rewritten)
- link_resolver.cleaned_link_target, path_lookup_forms, link_names_page, link_names_file, normalize_lookup_key (POS: a rename rewrites exactly the links the resolver points at the moved page)
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
from myrm_agent_harness.toolkits.wiki.core.link_extraction import (
    MARKDOWN_LINK_RE,
    WIKILINK_RE,
    is_external_link,
    parse_wikilink,
    protect_code,
)
from myrm_agent_harness.toolkits.wiki.core.link_resolver import (
    cleaned_link_target,
    link_names_file,
    link_names_page,
    normalize_lookup_key,
    path_lookup_forms,
)

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True, slots=True)
class _Move:
    """A rename or move being applied to the links of every other page."""

    old_path: Path
    new_path: Path
    old_slug: str
    new_slug: str
    is_dir: bool
    # Casefolded file names of every other page (file moves): a bare link naming one is ambiguous.
    other_leaves: frozenset[str]


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
        move = self._plan_move(old_path, new_path)

        for md_file in self.concepts_dir.rglob("*.md"):
            # Avoid refactoring within the moved files themselves if they were already moved
            if md_file == new_path or (new_path.is_dir() and new_path in md_file.parents):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                new_content = self._update_content_links(content, md_file, move)

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

    def _plan_move(self, old_path: Path, new_path: Path) -> _Move:
        is_dir = old_path.is_dir() or new_path.is_dir()
        other_leaves: set[str] = set()
        if not is_dir:
            moved = {old_path.resolve(), new_path.resolve()}
            moved_leaves = {normalize_lookup_key(old_path.stem), normalize_lookup_key(new_path.stem)}
            for page in self.concepts_dir.rglob("*.md"):
                leaf = normalize_lookup_key(page.stem)
                if leaf not in moved_leaves or page.resolve() not in moved:
                    other_leaves.add(leaf)
        return _Move(
            old_path=old_path,
            new_path=new_path,
            old_slug=_concept_slug_from_path(self.concepts_dir, old_path),
            new_slug=_concept_slug_from_path(self.concepts_dir, new_path),
            is_dir=is_dir,
            other_leaves=frozenset(other_leaves),
        )

    def _is_short_link_target(self, current_file: Path, forms: tuple[str, str], move: _Move) -> bool:
        """Whether a bare ``[[name]]`` held by ``current_file`` points at the moved page.

        The page beside the linking page wins; otherwise the name must be unique across
        the vault, the rule ``WikiLinkResolver`` applies to a bare file name.
        """
        old_resolved = move.old_path.resolve()

        # A sibling of the linking page that the name also matches is what the link points at.
        try:
            for sibling in current_file.parent.iterdir():
                if (
                    sibling.is_file()
                    and sibling.suffix.lower() == ".md"
                    and link_names_file(forms, sibling.stem)
                    and sibling.resolve() != old_resolved
                ):
                    return False
        except OSError:
            pass

        if move.old_path.parent.resolve() == current_file.parent.resolve():
            return True
        return not any(form in move.other_leaves for form in forms)

    def _renamed_wikilink_note(self, note: str, current_file: Path, current_slug: str, move: _Move) -> str | None:
        """The page part of a wikilink after the move, or ``None`` when the link is unaffected.

        A link is affected exactly when ``WikiLinkResolver`` would have pointed it at the
        moved page (or, for a folder move, at a page under the moved folder), whatever
        spelling it uses: path, sanitized path, vault prefix, relative path or bare file name.
        """
        cleaned = cleaned_link_target(note, current_slug)
        if cleaned is None:
            return None
        if move.is_dir:
            segments = [segment for segment in cleaned.split("/") if segment]
            depth = len(move.old_slug.split("/"))
            if len(segments) < depth or not link_names_page(
                path_lookup_forms("/".join(segments[:depth])), move.old_slug
            ):
                return None
            return "/".join([move.new_slug, *segments[depth:]])

        forms = path_lookup_forms(cleaned)
        if link_names_page(forms, move.old_slug):
            return move.new_slug
        if "/" in cleaned or not link_names_file(forms, move.old_path.stem):
            return None
        if not self._is_short_link_target(current_file, forms, move):
            return None
        if move.new_path.parent.resolve() == current_file.parent.resolve():
            return move.new_path.stem
        return move.new_slug

    def _update_content_links(self, content: str, current_file: Path, move: _Move) -> str:
        """Update markdown links and Obsidian wikilinks in content, preserving code blocks."""
        old_target, new_target, is_dir = move.old_path, move.new_path, move.is_dir
        masked, restore_code = protect_code(content)

        # 1. Update Markdown [text](url) links
        def _replace_markdown_link(match: re.Match[str]) -> str:
            text = match.group(1)
            url = match.group(2)
            if is_external_link(url):
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

        masked = MARKDOWN_LINK_RE.sub(_replace_markdown_link, masked)

        # 2. Update Obsidian [[wikilink]] targets
        current_slug = _concept_slug_from_path(self.concepts_dir, current_file)

        def _replace_wikilink(match: re.Match[str]) -> str:
            parts = parse_wikilink(match.group(1))
            new_note = self._renamed_wikilink_note(parts.note, current_file, current_slug, move)
            if new_note is None:
                return match.group(0)

            result_target = new_note + (".md" if parts.note.lower().endswith(".md") else "")
            if parts.fragment is not None:
                result_target = f"{result_target}#{parts.fragment}"
            if parts.label is not None:
                return f"[[{result_target}|{parts.label}]]"
            return f"[[{result_target}]]"

        return restore_code(WIKILINK_RE.sub(_replace_wikilink, masked))
