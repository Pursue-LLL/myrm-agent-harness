# [INPUT] RankedSnippetItem, SnippetTriageResult, TwoStageSearchConfig
# [OUTPUT] RankedSnippetTriageEngine
# [POS] Stage 1 lightweight snippet triage engine enforcing 500-token budget cap and meta-guidance

"""Ranked snippet triage engine strictly bounding Stage 1 context token usage."""

from __future__ import annotations

from urllib.parse import urlparse

from myrm_agent_harness.agent.context_management.two_stage_search_extract.search_extract_types import (
    RankedSnippetItem,
    SnippetTriageResult,
    TwoStageSearchConfig,
)


class RankedSnippetTriageEngine:
    """Triage engine pruning search results into compact, budget-capped snippets."""

    def __init__(self, config: TwoStageSearchConfig | None = None) -> None:
        self._config = config or TwoStageSearchConfig()

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract clean hostname or domain name from URL."""
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.split(":")[0]
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return netloc or "unknown"
        except Exception:
            return "unknown"

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Heuristic token estimate based on char count (~4 chars per token)."""
        if not text:
            return 0
        return max(1, (len(text) + 3) // 4)

    def extract_compact_snippet(self, raw_content: str) -> str:
        """Condense raw content into an 80-120 char high-density snippet."""
        clean = " ".join(raw_content.split()).strip()
        limit = self._config.snippet_char_limit
        if len(clean) <= limit:
            return clean

        truncated = clean[:limit].rstrip()
        # Ensure it does not end awkwardly mid-word if possible
        last_space = truncated.rfind(" ")
        if last_space > limit // 2:
            truncated = truncated[:last_space]
        return f"{truncated}..."

    def triage_candidates(
        self,
        query: str,
        raw_candidates: list[dict[str, str | float]],
    ) -> SnippetTriageResult:
        """Process raw candidates and bound output within token budget."""
        # Sort candidates descending by score if present
        sorted_candidates = sorted(
            raw_candidates,
            key=lambda c: float(c.get("score", 0.0)),
            reverse=True,
        )

        items: list[RankedSnippetItem] = []
        total_tokens = self.estimate_tokens(query) + self.estimate_tokens(
            self._config.default_guidance_directive
        )

        for idx, candidate in enumerate(sorted_candidates, start=1):
            title = str(candidate.get("title", "")).strip() or "Untitled"
            url = str(candidate.get("url", "")).strip()
            score = float(candidate.get("score", 0.0))
            raw_text = str(
                candidate.get("content")
                or candidate.get("snippet")
                or candidate.get("summary")
                or ""
            )

            snippet = self.extract_compact_snippet(raw_text)
            domain = self.extract_domain(url)

            # Estimate token footprint for this item
            item_text = f"{idx}. {title} ({domain}): {snippet} [{url}]"
            item_tokens = self.estimate_tokens(item_text)

            # Check if adding this item would exceed the budget cap (<= 500 tokens)
            if total_tokens + item_tokens > self._config.max_snippet_tokens_budget:
                if items:
                    # If we already have items, stop adding more to preserve token budget
                    break

            items.append(
                RankedSnippetItem(
                    index=idx,
                    title=title,
                    url=url,
                    domain=domain,
                    snippet=snippet,
                    relevance_score=score,
                    estimated_tokens=item_tokens,
                )
            )
            total_tokens += item_tokens

        return SnippetTriageResult(
            query=query,
            items=items,
            total_estimated_tokens=total_tokens,
            guidance_directive=self._config.default_guidance_directive,
            cached=False,
        )
