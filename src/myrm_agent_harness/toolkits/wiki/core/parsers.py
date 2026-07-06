"""LLM response parsers for concept extraction.

[INPUT]
json (POS: standard library JSON parser)
re (POS: standard library regex)
..core.types::ConceptInfo (POS: Wiki toolkit type definition)

[OUTPUT]
parse_concepts_response(): Parse LLM response into ConceptInfo list

[POS]
Parses LLM concept extraction responses in JSON or bullet-point format into
structured ConceptInfo objects.
"""

from __future__ import annotations

import json
import re

from .types import ConceptInfo


def parse_concepts_response(response: str, source_file: str) -> list[ConceptInfo]:
    """Parse LLM response into ConceptInfo list (supports JSON and bullet points)."""
    concepts: list[ConceptInfo] = []
    response_clean = response.strip()

    if response_clean.startswith("```json"):
        response_clean = response_clean[7:]
        if response_clean.endswith("```"):
            response_clean = response_clean[:-3]
        response_clean = response_clean.strip()
    elif response_clean.startswith("```"):
        response_clean = response_clean[3:]
        if response_clean.endswith("```"):
            response_clean = response_clean[:-3]
        response_clean = response_clean.strip()

    try:
        json_data = json.loads(response_clean)
        if isinstance(json_data, list):
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
    except (json.JSONDecodeError, KeyError):
        pass

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
