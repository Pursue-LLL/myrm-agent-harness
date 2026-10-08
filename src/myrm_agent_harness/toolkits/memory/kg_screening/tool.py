"""Agent-facing LangChain tool for knowledge graph pre-extraction content screening and anti-poisoning.

[INPUT]
- json
- langchain_core.tools::BaseTool, tool
- pydantic::BaseModel, Field
- toolkits.memory.kg_screening.shield::KnowledgeGraphPoisoningShield (POS: shield)
- toolkits.memory.kg_screening.types::ScreeningResult (POS: types)

[OUTPUT]
- ScreenKGExtractionContentInput: Pydantic input schema for runtime screening invocation
- create_kg_content_screening_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool allowing agents to verify candidate text compliance and strip prompt injections before graph triple extraction.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.kg_screening.shield import (
    KnowledgeGraphPoisoningShield,
)
from myrm_agent_harness.toolkits.memory.kg_screening.types import ScreeningResult


class ScreenKGExtractionContentInput(BaseModel):
    """Input parameters for pre-extraction content screening tool."""

    text: str = Field(..., min_length=1, description="Raw text candidate to be screened before knowledge graph extraction")
    source_uri: str | None = Field(default=None, description="Optional origin URL or document path")
    sanitize_if_possible: bool = Field(
        default=True,
        description="Whether to strip hidden HTML comments and zero-width characters instead of outright blocking",
    )


def create_kg_content_screening_tool(
    shield: KnowledgeGraphPoisoningShield | None = None,
) -> BaseTool:
    """Create a LangChain standard tool to screen and sanitize text before graph triple extraction."""
    active_shield = shield or KnowledgeGraphPoisoningShield()

    @tool("screen_kg_extraction_content", args_schema=ScreenKGExtractionContentInput)
    def screen_kg_extraction_content(
        text: str,
        source_uri: str | None = None,
        sanitize_if_possible: bool = True,
    ) -> str:
        """Screen and sanitize raw text against hidden HTML injection directives, system overrides, and memory poisoning before knowledge graph extraction."""
        result: ScreeningResult = active_shield.screen_text(
            text=text,
            source_uri=source_uri or "",
            sanitize_if_possible=sanitize_if_possible,
        )

        findings_payload = [
            {
                "category": f.category.value,
                "matched_pattern": f.matched_pattern,
                "snippet": f.snippet,
                "position": f.position,
                "risk_level": f.risk_level,
                "description": f.description,
            }
            for f in result.findings
        ]

        return json.dumps(
            {
                "verdict": result.verdict.value,
                "is_blocked": result.is_blocked,
                "findings": findings_payload,
                "original_length": result.original_length,
                "sanitized_content": result.sanitized_content,
                "risk_score": round(result.risk_score, 3),
            },
            ensure_ascii=False,
        )

    return screen_kg_extraction_content
