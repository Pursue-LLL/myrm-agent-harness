"""Typed result of a concept's bidirectional link lookup.

[INPUT]
- typing::TypedDict (POS: standard library types)

[OUTPUT]
- ConceptLink: one outgoing link (`name`, `exists`)
- ConceptBacklink: one incoming link, adding the snippet and section of the page that mentions the concept
- ConceptLinks: the lookup result; `outlinks_has_more` / `backlinks_has_more` say a direction was cut at the cap

[POS]
Payload contract between `WikiGraphStore.get_concept_links` and its callers; keys and value types are checked statically.
"""

from typing import TypedDict


class ConceptLink(TypedDict):
    name: str
    exists: bool


class ConceptBacklink(ConceptLink):
    context_snippet: str | None
    heading: str | None


class ConceptLinks(TypedDict):
    concept_name: str
    outlinks: list[ConceptLink]
    backlinks: list[ConceptBacklink]
    outlinks_has_more: bool
    backlinks_has_more: bool
