"""[INPUT]
- (none)

[OUTPUT]
- SearchResult: Unified search engine result model.
- Citation: Inline citation with positional info.

[POS]
Shared data models for web search results, used across the search toolkit.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.utils.text_cleaner import clean_text


class Citation(BaseModel):
    """Inline citation extracted from search results.

    Represents a URL citation with positional information within the response text,
    enabling precise source attribution and reference linking.
    """

    url: str = Field(..., description="Citation URL")
    title: str = Field(default="", description="Citation title")
    start_index: int | None = Field(default=None, description="Start character index in response text")
    end_index: int | None = Field(default=None, description="End character index in response text")


class SearchResult(BaseModel):
    """Unified search engine result model."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(..., description="Result heading")
    link: str = Field(..., description="Result URL")
    snippet: str = Field(..., description="Result summary snippet")
    date: str | None = Field(default=None, description="Published or last-updated date")
    is_error: bool = Field(default=False, description="Whether this result represents an error entry")
    engines: list[str] = Field(default_factory=list, description="Source search engines that returned this result")
    citations: list[Citation] = Field(default_factory=list, description="Inline citations with positional info")

    @property
    def url(self) -> str:
        """Alias for ``link`` for downstream API consistency."""
        return self.link

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchResult":
        """Build a SearchResult from a raw API response dict, applying content cleaning."""
        snippet = data.get("snippet", "") or data.get("content", "") or data.get("text", "")
        cleaned_snippet = clean_text(snippet)
        title = data.get("title") or "Untitled"

        result: dict[str, Any] = {
            "title": title,
            "link": data.get("link", "") or data.get("url", ""),
            "snippet": cleaned_snippet,
            "date": data.get("date"),
            "is_error": data.get("is_error", False),
            "engines": data.get("engines", []),
        }

        raw_citations = data.get("citations")
        if raw_citations and isinstance(raw_citations, list):
            parsed: list[Citation] = []
            for c in raw_citations:
                if isinstance(c, dict) and c.get("url"):
                    parsed.append(
                        Citation(
                            url=str(c["url"]),
                            title=str(c.get("title", "")),
                            start_index=c.get("start_index"),
                            end_index=c.get("end_index"),
                        )
                    )
            result["citations"] = parsed

        return cls(**result)
