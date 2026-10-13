"""Wiki link target resolution SSOT: wikilink / markdown-link targets to concept identities.

[INPUT]
- .structure::WikiStructure (POS: vault paths, concept path sanitization)
- myrm_agent_harness.utils.markdown_frontmatter::parse_frontmatter (POS: frontmatter parser)

[OUTPUT]
- normalize_wikilink_target, normalize_lookup_key, concept_link_name, page_lookup_keys
- scan_concept_pages, build_wikilink_title_index, wikilink_target_exists (POS: structural lint primitives)
- concept_index_key, concept_page_exists: index identity for a concept name, page presence check
- WikiLinkResolver: resolves link targets to canonical concept keys for graph edges

[POS]
A concept's canonical key is its vault-relative path without extension (the on-disk
identity). Structural lint and the graph index share these primitives, so a link that
lint accepts is stored as an edge to the page it points at.
"""

from __future__ import annotations

import posixpath
import threading
import time
from pathlib import Path, PurePath

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

logger = get_agent_logger(__name__)

_NON_CONCEPT_TARGET_PREFIXES = ("http://", "https://", "system:")
_VAULT_PATH_PREFIXES = ("wiki/", "concepts/")
_FRESHNESS_RECHECK_SECONDS = 300.0


def normalize_wikilink_target(raw_target: str) -> str:
    """Strip alias (`|`), heading anchor (`#`) and `.md` suffix from a wikilink target."""
    target = raw_target.split("|", maxsplit=1)[0].strip()
    if "#" in target:
        target = target.split("#", maxsplit=1)[0].strip()
    if target.lower().endswith(".md"):
        return target[:-3]
    return target


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
            logger.warning("Failed to index wikilink titles for %s: %s", concept_path, exc)
            continue
        pages[link_name] = page_lookup_keys(link_name, content)
    return pages


def _unique_key_index(pages: dict[str, frozenset[str]]) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for link_name, keys in pages.items():
        for key in keys:
            candidates.setdefault(key, []).append(link_name)
    return {key: names[0] for key, names in candidates.items() if len(names) == 1}


def build_wikilink_title_index(structure: WikiStructure) -> dict[str, str]:
    """Map normalized title / alias / canonical id / path keys to unique concept path slugs."""
    return _unique_key_index(scan_concept_pages(structure))


def wikilink_target_exists(
    structure: WikiStructure,
    target: str,
    title_index: dict[str, str],
) -> bool:
    if structure.resolve_concept_file_path(target) is not None:
        return True
    resolved_path = title_index.get(normalize_lookup_key(target))
    if resolved_path is None:
        return False
    return structure.resolve_concept_file_path(resolved_path) is not None


def _strip_vault_prefixes(path: str) -> str:
    for prefix in _VAULT_PATH_PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix) :]
    return path


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


class WikiLinkResolver:
    """Resolve link targets to canonical concept keys (vault-relative page paths).

    Resolution order: exact page path, sanitized page path, then a title / alias /
    canonical-id key that identifies exactly one page. Ambiguous or unknown targets
    return ``None`` so callers keep the raw text. Federated mounts are not resolved.

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
        self._fingerprint: tuple[int, int] = (0, 0)
        self._checked_at = 0.0

    def resolve(self, target: str, source: str | None = None) -> str | None:
        """Return the canonical key ``target`` points at, or ``None`` when unresolved.

        ``source`` enables explicit relative targets (``./x``, ``../x``) to be resolved
        against the linking page's directory.
        """
        cleaned = _strip_vault_prefixes(normalize_wikilink_target(target).replace("\\", "/"))
        if not cleaned or cleaned.startswith(_NON_CONCEPT_TARGET_PREFIXES):
            return None
        with self._lock:
            pages = self._fresh_pages()
            if source is not None and cleaned.startswith("."):
                cleaned = posixpath.normpath(posixpath.join(posixpath.dirname(source), cleaned))
            if cleaned in pages:
                return cleaned
            sanitized = WikiStructure._sanitize_path(cleaned)
            if sanitized in pages:
                return sanitized
            candidates = self._by_key.get(normalize_lookup_key(cleaned))
            if candidates is not None and len(candidates) == 1:
                return next(iter(candidates))
        return None

    def note_page(self, link_name: str, markdown: str) -> bool:
        """Record a written page; return True when stored edges may need re-resolving.

        That is the case when the page's lookup keys are new to this resolver or the
        page table was re-read from disk since the last call (other writers may have
        added pages). The table is read from disk, where the page being noted may
        already be present, so "new" is tracked per page by what was last reconciled.
        """
        with self._lock:
            pages = self._fresh_pages()
            rescanned, self._rescanned = self._rescanned, False
            keys = page_lookup_keys(link_name, markdown)
            if self._reconciled.get(link_name) == keys:
                return rescanned
            previous = pages.get(link_name)
            if previous is not None:
                self._drop_keys(link_name, previous)
            pages[link_name] = keys
            self._add_keys(link_name, keys)
            self._reconciled[link_name] = keys
            return True

    def forget_page(self, link_name: str) -> None:
        with self._lock:
            self._reconciled.pop(link_name, None)
            if self._pages is None:
                return
            previous = self._pages.pop(link_name, None)
            if previous is not None:
                self._drop_keys(link_name, previous)

    def _fresh_pages(self) -> dict[str, frozenset[str]]:
        now = time.monotonic()
        if self._pages is not None and now - self._checked_at < _FRESHNESS_RECHECK_SECONDS:
            return self._pages
        fingerprint = _vault_fingerprint(self._structure.concepts_dir)
        if self._pages is None or fingerprint != self._fingerprint:
            self._pages = scan_concept_pages(self._structure)
            self._by_key = {}
            for link_name, keys in self._pages.items():
                self._add_keys(link_name, keys)
            self._fingerprint = fingerprint
            self._rescanned = True
        self._checked_at = now
        return self._pages

    def _add_keys(self, link_name: str, keys: frozenset[str]) -> None:
        for key in keys:
            self._by_key.setdefault(key, set()).add(link_name)

    def _drop_keys(self, link_name: str, keys: frozenset[str]) -> None:
        for key in keys:
            owners = self._by_key.get(key)
            if owners is None:
                continue
            owners.discard(link_name)
            if not owners:
                del self._by_key[key]
