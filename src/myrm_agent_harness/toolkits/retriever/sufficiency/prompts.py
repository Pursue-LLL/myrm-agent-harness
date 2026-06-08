"""Sufficiency evaluation prompts.

[INPUT]
- (none — self-contained prompt templates)

[OUTPUT]
- SUFFICIENCY_EVAL_SYSTEM: System prompt for the evaluator LLM.
- SUFFICIENCY_EVAL_USER_TEMPLATE: User prompt template (format with query + snippets).
- SUFFICIENCY_JSON_SCHEMA: JSON Schema enforcing structured output.

[POS]
Prompt templates for the Retrieval Sufficiency Guard evaluator. Designed for
lightweight models (8B+) with JSON Schema enforcement to guarantee parseable output.
Includes negative constraint extraction as an integral part of evaluation.
"""

from __future__ import annotations

SUFFICIENCY_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "is_sufficient": {
            "type": "boolean",
            "description": "true if the snippets adequately answer ALL aspects of the query",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Your confidence in this judgment (0.0=guess, 1.0=certain)",
        },
        "missing_aspects": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific information gaps. Empty if sufficient.",
        },
        "suggested_queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Recommended search queries to fill identified gaps. Empty if sufficient.",
        },
        "negative_constraint_violations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Items in the snippets that violate the user's exclusion criteria (e.g. 'except X', 'not including Y'). Empty if no violations.",
        },
    },
    "required": ["is_sufficient", "confidence", "missing_aspects", "suggested_queries", "negative_constraint_violations"],
    "additionalProperties": False,
}

SUFFICIENCY_EVAL_SYSTEM = """\
You are a retrieval quality evaluator. Your job is to determine whether the \
retrieved snippets contain SUFFICIENT information to fully answer the user's query.

Rules:
1. Check if EVERY aspect of the query is covered by the snippets.
2. Identify any NEGATIVE CONSTRAINTS in the query (words like "except", "excluding", \
"not including", "other than", "除了", "不包括", "排除") and check if the snippets \
violate them.
3. If information is missing, suggest specific search queries that would fill the gaps.
4. Be conservative: mark as insufficient only when clearly important information is missing.
5. Output ONLY valid JSON matching the provided schema. No extra text."""

SUFFICIENCY_EVAL_USER_TEMPLATE = """\
## User Query
{query}

## Retrieved Snippets
{snippets}

## Task
Evaluate whether the retrieved snippets contain sufficient information to \
fully and accurately answer the user's query. Check for negative constraint \
violations. Respond with JSON only."""
