"""Wiki link target resolution SSOT: wikilink / markdown-link targets to concept identities.

[INPUT]
- .link_extraction::NON_PAGE_TARGET_PREFIXES, normalize_wikilink_target (POS: link syntax SSOT)
- .structure::WikiStructure (POS: vault paths, concept path sanitization)
- myrm_agent_harness.utils.markdown_frontmatter::parse_frontmatter (POS: frontmatter parser)

[OUTPUT]
- normalize_lookup_key, concept_link_name, page_lookup_keys
- cleaned_link_target, path_lookup_forms, link_lookup_forms, page_link_forms: the spellings a link target and a page are matched on (POS: keyed edge relinking, rename rewriting)
- link_names_page, link_names_file: whether a link names a page by path / by bare file name (POS: rename rewriting reads links as the resolver does)
- scan_concept_pages: lookup keys of every local concept page
- concept_index_key, concept_page_exists: index identity for a concept name, page presence check
- PageChange: what a written page changed for already stored edges
- WikiLinkResolver: resolves link targets to canonical concept keys for graph edges and structural lint

[POS]
A concept's canonical key is its vault-relative path without extension (the on-disk
identity). Graph edges and structural lint resolve link targets through the same
WikiLinkResolver, so a link lint accepts is stored as an edge to the page it points at.
Federated public pages are the exception: lint accepts them, edges keep their link text.
"""

from __future__ import annotations

import posixpath
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePath

from myrm_agent_harness.toolkits.wiki.core.link_extraction import (
    NON_PAGE_TARGET_PREFIXES,
    normalize_wikilink_target,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

logger = get_agent_logger(__name__)

_VAULT_PATH_PREFIXES = ("wiki/", "concepts/")
_FRESHNESS_RECHECK_SECONDS = 300.0


def normalize_lookup_key(key: str) -> str:
    return key.strip().casefold()


def concept_link_name(concept_path: Path, concepts_dir: Path) -> str:
    """Vault-relative concept path without extension (POSIX separators)."""
    rel = concept_path.relative_to(concepts_dir)
    return str(rel.with_suffix("")).replace("\\", "/")


def page_lookup_keys(link_name: str, markdown: str) -> frozenset[str]:
    """Casefolded keys a page answers to: its path, `title`, `aliases` and `canonical_id`."""
    keys = {normalize_lookup_key(link_name)}
    metadata, _body = parse_frontmatter(markdown)

    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        keys.add(normalize_lookup_key(title))

    raw_aliases = metadata.get("aliases")
    if isinstance(raw_aliases, list):
        keys.update(normalize_lookup_key(str(alias)) for alias in raw_aliases if str(alias).strip())
    elif isinstance(raw_aliases, str) and raw_aliases.strip():
        keys.add(normalize_lookup_key(raw_aliases))

    canonical_id = metadata.get("canonical_id")
    if isinstance(canonical_id, str) and canonical_id.strip():
        keys.add(normalize_lookup_key(canonical_id))
    return frozenset(keys)


def scan_concept_pages(structure: WikiStructure) -> dict[str, frozenset[str]]:
    """Map every local concept's link name to its lookup keys (federated mounts are skipped)."""
    pages: dict[str, frozenset[str]] = {}
    concepts_dir = structure.concepts_dir
    for concept_path in structure.list_concepts():
        if not concept_path.is_relative_to(concepts_dir):
            continue
        link_name = concept_link_name(concept_path, concepts_dir)
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read concept page %s for link resolution: %s", concept_path, exc)
            continue
        pages[link_name] = page_lookup_keys(link_name, content)
    return pages


def _strip_vault_prefixes(path: str) -> str:
    for prefix in _VAULT_PATH_PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix) :]
    return path


def cleaned_link_target(target: str, source: str | None = None) -> str | None:
    """Link target as a vault-relative path candidate, or ``None`` for non-concept targets.

    An explicit relative target (``./x``, ``../x``) is resolved against the directory of
    ``source``, the page that holds the link.
    """
    cleaned = _strip_vault_prefixes(normalize_wikilink_target(target).replace("\\", "/"))
    if not cleaned or cleaned.startswith(NON_PAGE_TARGET_PREFIXES):
        return None
    if source is not None and cleaned.startswith("."):
        return posixpath.normpath(posixpath.join(posixpath.dirname(source), cleaned))
    return cleaned


def path_lookup_forms(cleaned: str) -> tuple[str, str]:
    """The casefolded and the sanitized spelling of a cleaned link path."""
    return normalize_lookup_key(cleaned), WikiStructure._sanitize_path(cleaned)


def link_lookup_forms(target: str, source: str | None = None) -> tuple[str, str]:
    """The casefolded and the sanitized spelling every resolution tier matches a target on.

    Non-concept targets (URLs, ``system:*`` pseudo targets) have no forms: ``("", "")``.
    """
    cleaned = cleaned_link_target(target, source)
    return ("", "") if cleaned is None else path_lookup_forms(cleaned)


def link_names_page(forms: tuple[str, str], slug: str) -> bool:
    """Whether a link's ``forms`` name the page at ``slug`` by path, as resolution tiers 1 and 2 match it."""
    return forms[0] == normalize_lookup_key(slug) or forms[1] == slug


def link_names_file(forms: tuple[str, str], file_stem: str) -> bool:
    """Whether a link's ``forms`` name a page by its bare file name, as resolution tier 3 matches it."""
    return normalize_lookup_key(file_stem) in forms


def page_link_forms(link_name: str, keys: frozenset[str]) -> frozenset[str]:
    """Spellings a page answers to: its lookup keys and its casefolded file name."""
    return keys | {normalize_lookup_key(posixpath.basename(link_name))}


def concept_page_exists(structure: WikiStructure, key: str) -> bool:
    """Whether ``concepts_dir/<key>.md`` is a file inside the vault.

    Absolute keys, parent traversal and names the filesystem rejects are not pages.
    """
    key_path = PurePath(key)
    if key_path.is_absolute() or ".." in key_path.parts:
        return False
    try:
        return (structure.concepts_dir / f"{key}.md").is_file()
    except OSError:
        return False


def concept_index_key(structure: WikiStructure, name: str) -> str:
    """Index identity for ``name``: the on-disk concept path when a page exists for it.

    Compile names such as ``Knowledge/Rust/Ownership`` are written to
    ``knowledge/rust/ownership.md``; indexing them under that path keeps one index
    row per page. Names without a backing page (staged drafts, opaque keys) are
    returned unchanged.
    """
    clean = _strip_vault_prefixes(name.replace("\\", "/").strip()).removesuffix(".md")
    if not clean:
        return name
    safe = WikiStructure._sanitize_path(clean)
    if safe and concept_page_exists(structure, safe):
        return safe
    if concept_page_exists(structure, clean):
        return clean
    return name


def _vault_fingerprint(concepts_dir: Path) -> tuple[int, int]:
    """(file count, newest mtime) over the concept tree; detects out-of-band edits."""
    count = 0
    newest = 0
    for path in concepts_dir.rglob("*.md"):
        try:
            newest = max(newest, path.stat().st_mtime_ns)
        except OSError:
            continue
        count += 1
    return count, newest


@dataclass(frozen=True, slots=True)
class PageChange:
    """What a written page changed for edges that were stored before it existed.

    ``forms`` are the spellings the page answers to; only edges whose target is spelled
    like one of them can newly resolve. ``full_rescan`` means the resolver re-read the
    vault, so pages other writers added are unknown and every unresolved edge must be
    re-resolved.
    """

    forms: frozenset[str]
    full_rescan: bool


class WikiLinkResolver:
    """Resolve link targets to canonical concept keys (vault-relative page paths).

    Resolution order, first tier that names exactly one page wins:

    1. exact page path, then sanitized page path;
    2. a title / alias / canonical-id key that identifies one page;
    3. a bare file name (``[[Ownership]]``, ``[[Borrow Checker]]``, ``[[metric_gmv]]``),
       matched as written or sanitized: the page in the linking page's own folder
       wins, otherwise the name must be unique across the vault (the rule
       ``core.refactor`` applies when it renames a page).

    Ambiguous or unknown targets return ``None`` so callers keep the raw text. Federated
    mounts are not resolved.

    The page table is built lazily from disk, kept exact in-process through
    :meth:`note_page` / :meth:`forget_page`, and rebuilt when the vault changed behind
    the resolver's back (checked at most every ``_FRESHNESS_RECHECK_SECONDS``).
    """

    def __init__(self, structure: WikiStructure) -> None:
        self._structure = structure
        self._lock = threading.RLock()
        self._pages: dict[str, frozenset[str]] | None = None
        self._reconciled: dict[str, frozenset[str]] = {}
        self._rescanned = False
        self._by_key: dict[str, set[str]] = {}
        self._by_leaf: dict[str, set[str]] = {}
        self._fingerprint: tuple[int, int] = (0, 0)
        self._checked_at = 0.0

    def resolve(self, target: str, source: str | None = None) -> str | None:
        """Return the canonical key ``target`` points at, or ``None`` when unresolved.

        ``source`` is the page holding the link: it anchors explicit relative targets
        (``./x``, ``../x``) and picks the same-folder page for a bare file name.
        """
        cleaned = cleaned_link_target(target, source)
        if cleaned is None:
            return None
        with self._lock:
            pages = self._fresh_pages()
            if cleaned in pages:
                return cleaned
            sanitized = WikiStructure._sanitize_path(cleaned)
            if sanitized in pages:
                return sanitized
            key = normalize_lookup_key(cleaned)
            owners = self._by_key.get(key)
            if owners is not None and len(owners) == 1:
                return next(iter(owners))
            if "/" not in cleaned:
                return self._resolve_file_name((key, sanitized), source)
        return None

    def note_page(self, link_name: str, markdown: str) -> PageChange | None:
        """Record a written page; return what it changed when stored edges may need re-resolving.

        That is the case when the page's lookup keys are new to this resolver or the
        page table was re-read from disk since the last call (other writers may have
        added pages). The table is read from disk, where the page being noted may
        already be present, so "new" is tracked per page by what was last reconciled.
        """
        with self._lock:
            pages = self._fresh_pages()
            rescanned, self._rescanned = self._rescanned, False
            keys = page_lookup_keys(link_name, markdown)
            change = PageChange(page_link_forms(link_name, keys), full_rescan=rescanned)
            if self._reconciled.get(link_name) == keys:
                return change if rescanned else None
            previous = pages.get(link_name)
            if previous is not None:
                self._unindex_page(link_name, previous)
            pages[link_name] = keys
            self._index_page(link_name, keys)
            self._reconciled[link_name] = keys
            return change

    def forget_page(self, link_name: str) -> None:
        with self._lock:
            self._reconciled.pop(link_name, None)
            if self._pages is None:
                return
            previous = self._pages.pop(link_name, None)
            if previous is not None:
                self._unindex_page(link_name, previous)

    def _resolve_file_name(self, forms: tuple[str, str], source: str | None) -> str | None:
        owners = {name for form in forms for name in self._by_leaf.get(form, ())}
        if source is not None:
            folder = posixpath.dirname(source)
            siblings = {name for name in owners if posixpath.dirname(name) == folder}
            owners = siblings or owners
        return next(iter(owners)) if len(owners) == 1 else None

    def _fresh_pages(self) -> dict[str, frozenset[str]]:
        now = time.monotonic()
        if self._pages is not None and now - self._checked_at < _FRESHNESS_RECHECK_SECONDS:
            return self._pages
        fingerprint = _vault_fingerprint(self._structure.concepts_dir)
        if self._pages is None or fingerprint != self._fingerprint:
            self._pages = scan_concept_pages(self._structure)
            self._by_key = {}
            self._by_leaf = {}
            for link_name, keys in self._pages.items():
                self._index_page(link_name, keys)
            self._fingerprint = fingerprint
            self._rescanned = True
        self._checked_at = now
        return self._pages

    def _index_page(self, link_name: str, keys: frozenset[str]) -> None:
        for key in keys:
            self._by_key.setdefault(key, set()).add(link_name)
        self._by_leaf.setdefault(normalize_lookup_key(posixpath.basename(link_name)), set()).add(link_name)

    def _unindex_page(self, link_name: str, keys: frozenset[str]) -> None:
        _discard_owner(self._by_key, keys, link_name)
        _discard_owner(self._by_leaf, (normalize_lookup_key(posixpath.basename(link_name)),), link_name)


def _discard_owner(index: dict[str, set[str]], keys: Iterable[str], link_name: str) -> None:
    for key in keys:
        owners = index.get(key)
        if owners is None:
            continue
        owners.discard(link_name)
        if not owners:
            del index[key]
