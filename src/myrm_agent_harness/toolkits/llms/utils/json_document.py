"""Whether a model's text is a JSON document the structured-output parser accepts

[INPUT]
- langchain_core.utils.json::parse_json_markdown (POS: the JSON extraction ``JsonOutputParser`` applies)

[OUTPUT]
- is_json_document(): whether text parses to a JSON object or array, optionally inside a markdown fence

[POS]
Lets ``ChatLiteLLM`` decide on the same grounds as the output parser whether reasoning text can stand
in for an empty answer, so a chain of thought that merely mentions braces (or was cut off by the output
cap) takes the retry instead of failing the parser.
"""

from __future__ import annotations

from langchain_core.utils.json import parse_json_markdown


def is_json_document(text: str) -> bool:
    """Whether ``text`` is a JSON object or array, optionally inside a markdown fence."""
    try:
        return isinstance(parse_json_markdown(text), dict | list)
    except ValueError:
        return False
