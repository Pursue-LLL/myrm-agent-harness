"""[INPUT]
- (none)

[OUTPUT]
- SearchResult: Vector similarity search result.

[POS]
Provides SearchResult.
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
    """统一 Search引擎Result模型"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str = Field(..., description="SearchResultHeading")
    link: str = Field(..., description="SearchResultLink")
    snippet: str = Field(..., description="SearchResult摘要")
    date: str | None = Field(default=None, description="发布 or 最后Update日期")
    is_error: bool = Field(default=False, description="标记SearchResultWhether is Errorinformation")
    engines: list[str] = Field(default_factory=list, description="来源Search引擎List")
    citations: list[Citation] = Field(default_factory=list, description="Inline citations with positional info")

    @property
    def url(self) -> str:
        """GetURL， for compatible性

        Returns:
            LinkURL
        """
        return self.link

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchResult":
        """ from DictCreateSearchResultInstance，应用智能ContentClean up

        Args:
            data: ContainsSearchResultData Dict

        Returns:
            SearchResultInstance
        """
        # GetsnippetContent
        snippet = data.get("snippet", "") or data.get("content", "") or data.get("text", "")

        # 应用智能ContentClean up
        cleaned_snippet = clean_text(snippet)

        #  ensure title not  is None，保持originalHeading
        title = data.get("title") or " no Heading"

        # Extract基本Field
        result: dict[str, Any] = {
            "title": title,
            "link": data.get("link", "") or data.get("url", ""),
            "snippet": cleaned_snippet,
            "date": data.get("date"),  # Extract日期Field（IfExists）
            "is_error": data.get("is_error", False),
            "engines": data.get("engines", []),
        }

        # Parse citations if present
        raw_citations = data.get("citations")
        if raw_citations and isinstance(raw_citations, list):
            parsed: list[Citation] = []
            for c in raw_citations:
                if isinstance(c, dict) and c.get("url"):
                    parsed.append(Citation(
                        url=str(c["url"]),
                        title=str(c.get("title", "")),
                        start_index=c.get("start_index"),
                        end_index=c.get("end_index"),
                    ))
            result["citations"] = parsed

        return cls(**result)
