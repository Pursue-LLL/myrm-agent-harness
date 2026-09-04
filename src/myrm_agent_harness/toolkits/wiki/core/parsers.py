"""LLM response parsers for concept extraction.

[INPUT]
- utils.json_parsing::parse_llm_json_list (POS: robust JSON array extraction from LLM output)
- re (POS: standard library regex for bullet-point fallback)
- .core.types::ConceptInfo (POS: Wiki toolkit type definition)

[OUTPUT]
- parse_concepts_response: Parse LLM response into ConceptInfo list

[POS]
Parses LLM concept extraction responses in JSON or bullet-point format into
structured ConceptInfo objects.
"""

from __future__ import annotations

import re

from myrm_agent_harness.utils.json_parsing import parse_llm_json_list

from .types import ConceptInfo


def parse_concepts_response(response: str, source_file: str) -> list[ConceptInfo]:
    """Parse LLM response into ConceptInfo list (supports JSON and bullet points)."""
    concepts: list[ConceptInfo] = []
    response_clean = response.strip()

    json_data = parse_llm_json_list(response_clean)
    if json_data is not None:
        for item in json_data:
            if isinstance(item, dict) and "name" in item and "definition" in item:
                raw_related = item.get("related_concepts", [])
                related = [str(r) for r in raw_related] if isinstance(raw_related, list) else []
                concepts.append(
                    ConceptInfo(
                        name=item["name"],
                        definition=item["definition"],
                        mentions=1,
                        source_files=[source_file],
                        related_concepts=related,
                    )
                )
        return concepts

    for line in response_clean.split("\n"):
        line = line.strip()
        match = re.match(r"^(?:\d+\.|\-|\*)\s+(.*?)\s*(?:-|:|–)\s+(.*)", line)
        if match:
            name = match.group(1).replace("**", "").replace("*", "").strip()
            definition = match.group(2).strip()
            if name and definition:
                concepts.append(
                    ConceptInfo(
                        name=name,
                        definition=definition,
                        mentions=1,
                        source_files=[source_file],
                    )
                )

    return concepts
