"""Wiki link syntax SSOT: which links a page's prose holds and what they point at.

[INPUT]
- re (POS: standard library regular expressions)

[OUTPUT]
- CODE_REGION_RE, protect_code, mask_code: fenced and inline code is literal text, never a link
- WIKILINK_RE, MARKDOWN_LINK_RE: the two link syntaxes (each part at most 1024 characters, so an unclosed opener cannot make a scan quadratic)
- WikilinkParts, parse_wikilink, normalize_wikilink_target: split / normalize a `[[...]]` body
- NON_PAGE_TARGET_PREFIXES, is_external_link: targets that are not wiki pages
- find_wikilinks: page wikilinks with their source text and parts (label, heading)
- extract_wikilink_targets, extract_markdown_link_targets: distinct page-candidate targets of a page's prose

[POS]
Single definition of link syntax for graph edges, structural lint, move/rename refactoring,
backlink discovery and canvas import, so every consumer reads the same links in the same
text. Code regions (``` and ~~~ fences, backtick spans) are masked before any link is read;
a link may still wrap an inline code span in its label. Resolving a target to a page is
`link_resolver`'s concern, never this module's.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# Fences open on a line of their own (indented in list items; a backtick fence's info string has
# no backtick), close on a line of at least as many fence characters, and run to the end of the
# page when never closed. A backtick run anywhere else opens a span that ends at the next run of
# equal length within the same paragraph (CommonMark: spans may cross line breaks, not blank lines).
CODE_REGION_RE = re.compile(
    r"^[ \t]*(?P<backtick>`{3,})[^`\n]*$(?:\n[\s\S]*?^[ \t]*(?P=backtick)`*[ \t]*$|[\s\S]*\Z)"
    r"|^[ \t]*(?P<tilde>~{3,})[^\n]*(?:\n[\s\S]*?^[ \t]*(?P=tilde)~*[ \t]*$|[\s\S]*\Z)"
    r"|(?<!`)(?P<span>`+)(?!`)(?:(?!\n[ \t]*\n)[\s\S])+?(?<!`)(?P=span)(?!`)",
    re.MULTILINE,
)
# Link parts are length-bounded: an opener without its closer (`[[`, `[x](`) would otherwise
# rescan the rest of the line, or page, from every opener, which is quadratic in page size.
_MAX_LINK_PART = 1024
WIKILINK_RE = re.compile(rf"\[\[([^\]\n]{{1,{_MAX_LINK_PART}}})\]\]")
MARKDOWN_LINK_RE = re.compile(rf"\[([^\]]{{1,{_MAX_LINK_PART}}})\]\(([^)]{{1,{_MAX_LINK_PART}}})\)")

NON_PAGE_TARGET_PREFIXES = ("http://", "https://", "system:")

_EXTERNAL_LINK_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]+:|#|//)")
_CODE_TOKEN_RE = re.compile(r"\x00(\d+)\x00")


def protect_code(content: str) -> tuple[str, Callable[[str], str]]:
    """Replace code regions with opaque tokens; return the masked text and the inverse.

    Link regexes run on the masked text and never see code. The inverse restores the
    original code in any text derived from it.
    """
    if "`" not in content and "~~~" not in content:
        return content, _identity

    regions: list[str] = []

    def _save(match: re.Match[str]) -> str:
        regions.append(match.group(0))
        return f"\x00{len(regions) - 1}\x00"

    masked = CODE_REGION_RE.sub(_save, content)

    def _restore(text: str) -> str:
        return _CODE_TOKEN_RE.sub(lambda token: regions[int(token.group(1))], text)

    return masked, _restore


def mask_code(content: str) -> str:
    """``content`` with every code region replaced by an opaque token."""
    return protect_code(content)[0]


def _identity(text: str) -> str:
    return text


@dataclass(frozen=True, slots=True)
class WikilinkParts:
    """A `[[note#fragment|label]]` body split into its parts (fragment/label are None when absent)."""

    note: str
    fragment: str | None
    label: str | None


def parse_wikilink(inner: str) -> WikilinkParts:
    """Split a wikilink body on its first `|` (label), then on the first `#` (heading)."""
    target, bar, label = inner.partition("|")
    note, hash_mark, fragment = target.partition("#")
    return WikilinkParts(note.strip(), fragment if hash_mark else None, label if bar else None)


def normalize_wikilink_target(raw_target: str) -> str:
    """Page target of a wikilink body: no label, no heading anchor, no `.md` suffix."""
    note = parse_wikilink(raw_target).note
    return note[:-3] if note.lower().endswith(".md") else note


def is_external_link(url: str) -> bool:
    """Whether a markdown link target leaves the vault: URL scheme, `//host`, or same-page `#anchor`."""
    return _EXTERNAL_LINK_RE.match(url.strip()) is not None


def _is_page_reference(target: str) -> bool:
    """Whether masked link text names a page: not empty, not code, not a URL or pseudo target."""
    return bool(target) and "\x00" not in target and not target.startswith(NON_PAGE_TARGET_PREFIXES)


def find_wikilinks(content: str) -> list[tuple[str, WikilinkParts]]:
    """(source text, parts) of every page `[[wikilink]]` outside code, in order of appearance.

    Same-page anchors (`[[#Heading]]`), empty bodies, URLs and `system:*` pseudo targets
    are not page references and are dropped. A label may wrap inline code.
    """
    masked, restore = protect_code(content)
    found: list[tuple[str, WikilinkParts]] = []
    for match in WIKILINK_RE.finditer(masked):
        parts = parse_wikilink(match.group(1))
        if _is_page_reference(parts.note):
            fragment = None if parts.fragment is None else restore(parts.fragment)
            label = None if parts.label is None else restore(parts.label)
            found.append((restore(match.group(0)), WikilinkParts(parts.note, fragment, label)))
    return found


def extract_wikilink_targets(content: str) -> tuple[str, ...]:
    """Distinct page targets of the `[[wikilinks]]` outside code, in order of appearance."""
    targets: dict[str, None] = {}
    for match in WIKILINK_RE.finditer(mask_code(content)):
        target = normalize_wikilink_target(match.group(1))
        if _is_page_reference(target):
            targets[target] = None
    return tuple(targets)


def extract_markdown_link_targets(content: str) -> tuple[str, ...]:
    """Distinct vault-relative paths of the `[text](path)` links outside code, without `#fragment`.

    External links and same-page anchors are not paths in the vault and are dropped.
    """
    paths: dict[str, None] = {}
    for match in MARKDOWN_LINK_RE.finditer(mask_code(content)):
        url = match.group(2).strip()
        if is_external_link(url):
            continue
        path = url.partition("#")[0].strip()
        if path and "\x00" not in path:
            paths[path] = None
    return tuple(paths)
