"""Related Concepts section SSOT: the one writer of a page's related-link bullets.

[INPUT]
- .link_extraction::extract_wikilink_targets, normalize_wikilink_target (POS: link syntax SSOT)
- .link_resolver::WikiLinkResolver, normalize_lookup_key (POS: link target to page identity)
- .section_contract::get_section_inner, replace_section_inner (POS: section-aware page edits)

[OUTPUT]
- RELATED_HEADING: the section heading
- merge_related_links: add the links a page lacks to its Related Concepts section

[POS]
Compile-time backlinks and maintenance link discovery both add links here, so neither
rewrites the rest of the page. Only the Related Concepts section is edited, and only by
appending: text and links already in it stay as they are. A link counts as present when it
names a page the section already links, however it is spelled; a page is never listed as
related to itself. Names come from model output, so a name that cannot be a single-line
wikilink target is dropped instead of written into the page.
"""

from __future__ import annotations

from collections.abc import Iterable

from myrm_agent_harness.toolkits.wiki.core.link_extraction import (
    extract_wikilink_targets,
    normalize_wikilink_target,
)
from myrm_agent_harness.toolkits.wiki.core.link_resolver import WikiLinkResolver, normalize_lookup_key
from myrm_agent_harness.toolkits.wiki.core.section_contract import get_section_inner, replace_section_inner

RELATED_HEADING = "## Related Concepts"


def _is_link_target(name: str) -> bool:
    """Whether ``name`` fits inside one ``[[...]]`` on one line."""
    return len(name.splitlines()) == 1 and "[" not in name and "]" not in name


def _link_identity(resolver: WikiLinkResolver, target: str, source: str) -> str:
    """The page ``target`` points at, or its casefolded spelling when it names no single page."""
    return resolver.resolve(target, source) or normalize_lookup_key(normalize_wikilink_target(target))


def merge_related_links(
    content: str,
    names: Iterable[str],
    *,
    source: str,
    resolver: WikiLinkResolver,
) -> tuple[str, int]:
    """Return ``content`` with ``names`` linked from its Related Concepts section, and how many were added.

    ``source`` is the vault-relative key of the page holding the links. Names that are blank,
    cannot be a link target, name the page itself or name a page the section already links are
    skipped; ``content`` comes back unchanged when nothing is added.
    """
    existing = get_section_inner(content, RELATED_HEADING) or ""
    present = {_link_identity(resolver, target, source) for target in extract_wikilink_targets(existing)}
    present.add(source)

    bullets: list[str] = []
    for name in names:
        link = name.strip()
        if not link or not _is_link_target(link):
            continue
        identity = _link_identity(resolver, link, source)
        if identity in present:
            continue
        present.add(identity)
        bullets.append(f"- [[{link}]]")

    if not bullets:
        return content, 0
    inner = "\n".join(filter(None, [existing.rstrip("\n"), *bullets]))
    return replace_section_inner(content, RELATED_HEADING, inner), len(bullets)
