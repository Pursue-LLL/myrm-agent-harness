"""Search intent detection and parameter optimization.

Zero-LLM-cost query intent classification that dynamically adjusts search
engine parameters (categories, engines, time_range) for improved result
relevance. Provider-aware for SearxNG, Tavily, and Volcengine Doubao.

[INPUT]
- (none)

[OUTPUT]
- SearchIntent: Query intent categories for search parameter optimization.
- SearchIntentResult: Intent detection result with confidence score.
- SearchIntentDetector: Protocol for intent detection strategies.
- KeywordSearchIntentDetector: Default keyword-based implementation (zero LLM cost).
- extract_and_pin_structured_identifiers: Zero-cost identifier slot extraction and exact phrase pinning.
- resolve_search_params: Maps intent + provider to optimal search parameters (incl. AUTHORITY→Volcengine AuthInfoLevel).

[POS]
Search intent detection and parameter optimization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from myrm_agent_harness.toolkits.web_search.providers.web_searcher import SearchServiceType


class SearchIntent(Enum):
    """Query intent categories for search parameter optimization."""

    CODE = "code"
    NEWS = "news"
    FINANCE = "finance"
    ACADEMIC = "academic"
    SOCIAL = "social"
    SECURITY = "security"
    AUTHORITY = "authority"
    PLATFORM_BILIBILI = "platform_bilibili"
    GENERAL = "general"


@dataclass(frozen=True, slots=True)
class SearchIntentResult:
    """Intent detection result.

    Attributes:
        intent: Detected query intent
        confidence: Detection confidence (0.0-1.0); below threshold falls back to GENERAL
    """

    intent: SearchIntent
    confidence: float


class SearchIntentDetector(Protocol):
    """Protocol for search intent detection strategies."""

    def detect(self, query: str) -> SearchIntentResult:
        """Detect search intent from a query string.

        Args:
            query: Search query (typically after LLM rewriting)

        Returns:
            Intent detection result with confidence score
        """
        ...


# Confidence threshold: below this, fall back to GENERAL (no adjustment)
_CONFIDENCE_THRESHOLD = 0.6

# Intent keyword patterns (order matters: first match wins within a group)
# Priority groups ensure e.g. "Python news" matches NEWS not CODE
# Note: \b does not work for CJK characters; Chinese patterns omit \b.
_PRIORITY_PATTERNS: list[tuple[SearchIntent, list[str]]] = [
    # PLATFORM_BILIBILI has highest priority (explicit platform routing)
    (
        SearchIntent.PLATFORM_BILIBILI,
        [
            r"(?:搜|找|查|看看|搜索)B站",
            r"B站(?:上|里|中|内)?(?:搜|找|查|有没有|有哪些|关于)",
            r"(?:搜|找|查|看看|搜索)(?:b站|哔哩哔哩)",
            r"(?:b站|哔哩哔哩)(?:上|里|中|内)?(?:搜|找|查|有没有|有哪些|关于)",
            r"\bsite:bilibili\.com\b",
        ],
    ),
    # NEWS has highest priority (overrides language-name matches)
    (
        SearchIntent.NEWS,
        [
            r"\b(news|latest|breaking|announce|announced|release[ds]?|launch|update[ds]?)\b",
            r"(今[日天]|最新|新闻|动态|发布|更新|上线|官宣)",
            r"\b(yesterday|today|this week|this month)\b",
            r"(昨[天日]|本周|本月|近期|刚[刚才])",
        ],
    ),
    # FINANCE
    (
        SearchIntent.FINANCE,
        [
            r"\b(stock|price|market|valuation|funding|ipo|revenue|earnings)\b",
            r"(估值|股[价票权]|市[值场]|融资|营收|财报|基金|利率|汇率|投[资融])",
            r"\b(nasdaq|nyse|s&p|dow|bitcoin|btc|eth|crypto)\b",
            r"(a股|港股|美股|加密|币[价圈])",
        ],
    ),
    # AUTHORITY (official / authoritative sources — Volcengine AuthInfoLevel)
    (
        SearchIntent.AUTHORITY,
        [
            r"\b(official\s+(?:site|website|docs?|documentation|source|announcement))\b",
            r"\b(authoritative|government|gov\.|\.gov\b)\b",
            r"(官方|权威|官网|政府|部委|白皮书|正规来源)",
            r"\bsite:(?:gov|edu)\.",
        ],
    ),
    # SECURITY
    (
        SearchIntent.SECURITY,
        [
            r"\b(cve|vulnerability|exploit|malware|threat|ioc|ip\s*reputation)\b",
            r"(漏洞|威胁|恶意|攻击|渗透|注入|xss|sql injection)",
            r"\b(virustotal|shodan|abuseipdb|mitre|att&ck)\b",
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
        ],
    ),
    # ACADEMIC
    (
        SearchIntent.ACADEMIC,
        [
            r"\b(paper|papers|arxiv|research|journal|conference|thesis|doi)\b",
            r"(论文|学术|研究|期刊|会议|摘要|引用|学者)",
            r"\b(icml|neurips|iclr|cvpr|acl|emnlp|sigmod|vldb)\b",
        ],
    ),
    # CODE (lower priority than NEWS to avoid "Python news" misclassification)
    (
        SearchIntent.CODE,
        [
            r"\b(github|stackoverflow|implementation|source\s*code|repository|crate|package)\b",
            r"(代码|实现|仓库|源码|开源|框架|库)",
            r"\b(npm|pypi|crates\.io|cargo|pip install|go get)\b",
            r"\b(function|class|struct|interface|async|await|impl)\b",
            r"\b(rust|golang|typescript|kotlin|swift)\b(?=.*\b(code|impl|example|how)\b)",
        ],
    ),
    # SOCIAL
    (
        SearchIntent.SOCIAL,
        [
            r"\b(reddit|twitter|x\.com|hacker\s*news|forum|community|discussion)\b",
            r"(论坛|社区|讨论|帖子|评论|口碑|评价|反馈)",
        ],
    ),
]


class KeywordSearchIntentDetector:
    """Keyword-based search intent detector (zero LLM cost).

    Uses regex pattern matching with priority-ordered intent groups.
    Supports both English and Chinese keywords.
    Falls back to GENERAL when confidence is below threshold.
    """

    def detect(self, query: str) -> SearchIntentResult:
        """Detect intent via keyword/regex matching.

        Priority-based: earlier groups in _PRIORITY_PATTERNS take precedence.
        Multiple pattern matches within a group increase confidence.
        """
        query_lower = query.lower()

        for intent, patterns in _PRIORITY_PATTERNS:
            match_count = sum(1 for pattern in patterns if re.search(pattern, query_lower, re.IGNORECASE))
            if match_count > 0:
                confidence = min(0.5 + match_count * 0.2, 1.0)
                return SearchIntentResult(intent=intent, confidence=confidence)

        return SearchIntentResult(intent=SearchIntent.GENERAL, confidence=1.0)


# Provider-specific parameter mappings
# Key: (SearchIntent, SearchServiceType) -> extra_params override
_SEARXNG_INTENT_PARAMS: dict[SearchIntent, dict[str, str]] = {
    SearchIntent.CODE: {
        "engines": "github,stackoverflow,npm,pypi",
        "categories": "it",
    },
    SearchIntent.NEWS: {
        "engines": "google news,bing news,duckduckgo",
        "categories": "news",
        "time_range": "day",
    },
    SearchIntent.FINANCE: {
        "categories": "general",
        "time_range": "week",
    },
    SearchIntent.ACADEMIC: {
        "engines": "arxiv,google scholar,semantic scholar",
        "categories": "science",
    },
    SearchIntent.SOCIAL: {
        "engines": "reddit,hackernews,google",
        "categories": "social media",
    },
    SearchIntent.SECURITY: {
        "categories": "it",
        "time_range": "year",
    },
    SearchIntent.AUTHORITY: {
        "categories": "general",
    },
    # GENERAL: no override (use user's default config)
}

_TAVILY_INTENT_PARAMS: dict[SearchIntent, dict[str, str]] = {
    SearchIntent.NEWS: {"topic": "news"},
    SearchIntent.FINANCE: {"topic": "finance"},
}

_VOLCENGINE_DOUBAO_INTENT_PARAMS: dict[SearchIntent, dict[str, str | bool | int]] = {
    SearchIntent.NEWS: {"TimeRange": "OneDay", "QueryRewrite": True},
    SearchIntent.FINANCE: {"TimeRange": "OneWeek"},
    SearchIntent.SECURITY: {"TimeRange": "OneWeek"},
    SearchIntent.AUTHORITY: {"AuthInfoLevel": 1},
}


def resolve_search_params(
    intent_result: SearchIntentResult,
    provider: SearchServiceType,
) -> dict[str, str | bool] | None:
    """Resolve optimal search parameters based on detected intent and provider.

    Returns None when no adjustment should be made (GENERAL intent or low confidence).

    Args:
        intent_result: Result from SearchIntentDetector
        provider: Current search service provider type

    Returns:
        Extra parameters override dict, or None if no adjustment needed
    """
    if intent_result.intent == SearchIntent.GENERAL:
        return None
    if intent_result.confidence < _CONFIDENCE_THRESHOLD:
        return None

    if provider == "searxng":
        return _SEARXNG_INTENT_PARAMS.get(intent_result.intent)
    elif provider == "tavily":
        return _TAVILY_INTENT_PARAMS.get(intent_result.intent)
    elif provider == "volcengine_doubao":
        return _VOLCENGINE_DOUBAO_INTENT_PARAMS.get(intent_result.intent)

    return None


# Module-level singleton detector instance
_default_detector = KeywordSearchIntentDetector()


# Common structured identifier regex patterns for zero-LLM-cost slot extraction
_CVE_PATTERN = re.compile(r"\b(CVE-\d{4}-\d{4,7})\b", re.IGNORECASE)
_DOI_PATTERN = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")
_STOCK_SYMBOL_PATTERN = re.compile(
    r"\b(?:stock|quote|ticker|symbol|shares?|纳斯达克|美股|港股|A股)[\s:]+([A-Z0-9.]{1,8})\b"
    r"|\b([A-Z]{2,5})\b(?=[\s]+(?:stock|quote|shares?|earnings|财报|股价))",
    re.IGNORECASE,
)


def extract_and_pin_structured_identifiers(query: str) -> tuple[str, list[str]]:
    """Extract structured domain identifiers (CVE, DOI, stock codes) and pin them with quotes.

    Ensures critical domain identifiers are not fragmented by tokenizer/search engine
    without adding extra LLM turn or latency overhead.

    Args:
        query: The raw rewritten search query string.

    Returns:
        tuple of (pinned_query, extracted_identifiers).
    """
    if not query or not query.strip():
        return query, []

    pinned_ids: list[str] = []
    modified_query = query

    # 1. CVE identifier extraction and exact pinning
    for match in _CVE_PATTERN.finditer(query):
        cve_id = match.group(1).upper()
        if cve_id not in pinned_ids:
            pinned_ids.append(cve_id)
            # Avoid duplicate quotes if already quoted
            raw_match = match.group(1)
            if f'"{raw_match}"' not in modified_query and f"'{raw_match}'" not in modified_query:
                modified_query = re.sub(rf"\b{re.escape(raw_match)}\b", f'"{cve_id}"', modified_query)

    # 2. DOI identifier extraction and exact pinning
    for match in _DOI_PATTERN.finditer(query):
        doi_id = match.group(1)
        if doi_id not in pinned_ids:
            pinned_ids.append(doi_id)
            if f'"{doi_id}"' not in modified_query and f"'{doi_id}'" not in modified_query:
                modified_query = modified_query.replace(doi_id, f'"{doi_id}"')

    # 3. Stock ticker extraction
    for match in _STOCK_SYMBOL_PATTERN.finditer(query):
        symbol = (match.group(1) or match.group(2) or "").upper()
        if symbol and len(symbol) >= 2 and symbol not in pinned_ids:
            pinned_ids.append(symbol)
            raw_sym = match.group(1) or match.group(2)
            if f'"{raw_sym}"' not in modified_query and f"'{raw_sym}'" not in modified_query:
                modified_query = re.sub(rf"\b{re.escape(raw_sym)}\b", f'"{symbol}"', modified_query)

    return modified_query, pinned_ids


def detect_search_intent(query: str) -> SearchIntentResult:
    """Convenience function using the default keyword-based detector.

    Args:
        query: Search query string

    Returns:
        Intent detection result
    """
    return _default_detector.detect(query)

