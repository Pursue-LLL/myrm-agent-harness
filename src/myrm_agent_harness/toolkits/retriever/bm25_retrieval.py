"""BM25 sparse retrieval implementation.

Keyword-matching retrieval based on the BM25 algorithm with smart CJK/English hybrid tokenization.

[INPUT]
rank_bm25::BM25Okapi (POS: BM25 scoring algorithm)
retriever.bm25::get_tokenizer_service (POS: Unified tokenization service for CJK/English)

[OUTPUT]
extract_version_tokens: Generates hierarchical version-number tokens for version-aware search
BM25Retrieval: Stateful BM25 index that supports build / query / incremental add / remove

[POS]
BM25 sparse retrieval engine. Builds an in-memory inverted index from document chunks and
returns keyword-matched results ranked by BM25 score.

"""

import logging
import re
import time
import warnings

from rank_bm25 import BM25Okapi

from myrm_agent_harness.toolkits.retriever.bm25 import get_tokenizer_service

# Suppress jieba pkg_resources deprecation warning
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API.*", category=UserWarning)

logger = logging.getLogger(__name__)


def extract_version_tokens(version: str) -> list[str]:
    """Generate hierarchical and individual-digit tokens from a version number.

    Supports version inheritance relationships and fine-grained matching.

    Args:
        version: Version number string, e.g., "1.77.2"

    Returns:
        List of hierarchical tokens and individual digit tokens

    Examples:
        >>> extract_version_tokens("1.77.2")
        ['1.77.2', '1.77', '1', '77', '2']

        >>> extract_version_tokens("1.77.0-alpha.1")
        ['1.77.0-alpha.1', '1.77.0', '1.77', '1', '77', '0']
    """
    if not version:
        return []

    tokens = [version]  # Full version string

    # Clean version: strip prefix and suffix identifiers
    clean_version = version
    clean_version = re.sub(r"^v", "", clean_version)
    clean_version = re.sub(r"[-+].*$", "", clean_version)  # Strip suffixes like -alpha.1, +build.123

    if clean_version != version:
        tokens.append(clean_version)

    # Split version into components
    parts = clean_version.split(".")

    # Generate parent version numbers
    for i in range(len(parts) - 1, 1, -1):
        parent_version = ".".join(parts[:i])
        if parent_version and parent_version not in tokens:
            tokens.append(parent_version)

    # Generate individual digit tokens for fine-grained matching
    for part in parts:
        if part and part.isdigit() and part not in tokens:
            tokens.append(part)

    return tokens


def extract_url_keywords(url: str) -> list[str]:
    """Extract keywords from a URL, including product names, path info, and fragment anchors.

    Args:
        url: URL string

    Returns:
        List of keywords extracted from the URL
    """
    keywords = []

    # Extract product names from domain, including subdomains
    domain_patterns = [
        r"([a-z]+)\.([a-z]+)\.ai",  # docs.litellm.ai -> docs, litellm
        r"([a-z]+)\.([a-z]+)\.com",  # api.example.com -> api, example
        r"([a-z]+)\.ai",  # litellm.ai -> litellm
        r"([a-z]+)\.com",  # example.com -> example
        r"([a-z]+)\.org",  # example.org -> example
    ]

    for pattern in domain_patterns:
        matches = re.findall(pattern, url.lower())
        for match in matches:
            if isinstance(match, tuple):
                keywords.extend(match)
            else:
                keywords.append(match)

    # Extract keywords from path segments
    path_keywords = re.findall(r"/([a-z0-9_\-]+)", url.lower())
    for keyword in path_keywords:
        keywords.append(keyword)

        # Decompose underscore/hyphen-connected words
        if "_" in keyword or "-" in keyword:
            normalized = keyword.replace("-", "_")
            parts = normalized.split("_")
            keywords.extend(parts)

        # Extract version number patterns, e.g., v1-77-2 -> v1, 77, 2
        version_match = re.match(r"v?(\d+)[-_]?(\d+)[-_]?(\d+)?", keyword)
        if version_match:
            for group in version_match.groups():
                if group:
                    keywords.append(group)

    # Extract keywords from fragment (part after #)
    # e.g., https://docs.langchain.com/agents#system-prompt -> system, prompt
    fragment_match = re.search(r"#([a-z0-9_\-]+)", url.lower())
    if fragment_match:
        fragment = fragment_match.group(1)
        keywords.append(fragment)

        # Decompose underscore/hyphen-connected parts
        if "_" in fragment or "-" in fragment:
            normalized = fragment.replace("-", "_")
            parts = normalized.split("_")
            keywords.extend(parts)

    return keywords


def split_camelcase(text: str) -> list[str]:
    """Split camelCase identifiers and brand names into components.

    Args:
        text: Input text

    Returns:
        List of split tokens

    Examples:
        >>> split_camelcase("LiteLLM")
        ['LiteLLM', 'Lite', 'LLM']

        >>> split_camelcase("FastAPI")
        ['FastAPI', 'Fast', 'API']

        >>> split_camelcase("GitHub")
        ['GitHub', 'Git', 'Hub']
    """
    if not text:
        return []

    tokens = [text]  # Keep original token

    # Extract consecutive uppercase sequences (e.g., API, LLM)
    consecutive_caps = re.findall(r"[A-Z]{2,}", text)
    tokens.extend(consecutive_caps)

    # CamelCase split: extract segments starting with uppercase followed by lowercase
    camel_parts = re.findall(r"[A-Z][a-z]+", text)
    tokens.extend(camel_parts)

    # Special brand name handling
    brand_mappings = {
        "github": ["git", "hub"],
        "gitlab": ["git", "lab"],
        "pytorch": ["py", "torch"],
        "tensorflow": ["tensor", "flow"],
        "javascript": ["java", "script"],
        "typescript": ["type", "script"],
        "nodejs": ["node", "js"],
        "reactjs": ["react", "js"],
        "vuejs": ["vue", "js"],
    }

    lower_text = text.lower()
    if lower_text in brand_mappings:
        tokens.extend(brand_mappings[lower_text])

    return tokens


def extract_special_patterns(text: str) -> list[str]:
    """Extract special patterns: version numbers, URLs, emails, etc., with hierarchical version tokens.

    Args:
        text: Raw text

    Returns:
        List of extracted special-pattern tokens; version numbers include hierarchical tokens
    """
    patterns = [
        # Enhanced version patterns: supports pre-release, semantic versioning, etc.
        (r"v?\d+\.\d+(?:\.\d+)*(?:[-+](?:alpha|beta|rc|dev|pre|snapshot)(?:\.\d+)?)?(?:\+[a-z0-9\.\-]+)?", "version"),
        (r"version[-_]?\d+\.\d+(?:\.\d+)*", "version"),  # version-1.77.2
        (r"\d{4}\.\d{2}\.\d{2}", "date_version"),  # Date version 2024.01.15
        (r"https?://[^\s]+", "url"),  # Full URL
        (r"\w+\.\w+(?:\.\w+)*(?:/[^\s]*)?", "domain_url"),  # Domain-style URL
        (r"\w+@\w+\.\w+", "email"),
        (r"\d{4}-\d{2}-\d{2}", "date"),
        (r"\w+[-_]\w+(?:[-_]\w+)*", "identifier"),
        (r"[A-Z]{2,}", "acronym"),
        (r"[A-Z][a-z]+(?:[A-Z][a-z]*)+", "camelcase"),
    ]

    special_tokens = []

    for pattern, pattern_type in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if pattern_type == "version" or pattern_type == "date_version":
                version_tokens = extract_version_tokens(match)
                special_tokens.extend(version_tokens)
            elif pattern_type == "url" or pattern_type == "domain_url":
                special_tokens.append(match)
                url_keywords = extract_url_keywords(match)
                special_tokens.extend(url_keywords)
            elif pattern_type == "camelcase":
                camel_tokens = split_camelcase(match)
                special_tokens.extend(camel_tokens)
            else:
                special_tokens.append(match)

    return special_tokens


def preprocess_text(text: str, enable_english_enhancement: bool = False) -> list[str]:
    """Enhanced tokenization strategy integrating special pattern extraction.

    Supports version numbers, URLs, and other intelligent tokenization patterns.

    Args:
        text: Raw text
        enable_english_enhancement: Whether to enable stemming and stopword filtering for English

    Returns:
        List of tokens

    Examples:
        >>> preprocess_text("litellm 1.77 release notes")
        ['litellm', '1.77', '1', '77', 'release', 'notes', 'litellmreleasenotes']

        >>> preprocess_text("docs.litellm.ai/release_notes/v1-77-2")
        ['docs.litellm.ai/release_notes/v1-77-2', 'docs', 'litellm', 'release_notes',
         'release', 'notes', 'v1-77-2', '1', '77', '2']
    """
    if not text:
        return []

    tokenizer = get_tokenizer_service()
    tokens = []

    # 1. Extract special patterns (versions, URLs, camelCase) before lowering
    special_tokens = extract_special_patterns(text)
    tokens.extend(special_tokens)

    # 2. Convert to lowercase
    text = text.lower()

    # 3. Remove special characters, keeping letters, digits, CJK chars, and spaces
    cleaned_text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)

    # 4. Process each word
    for word in cleaned_text.split():
        if not word.strip():
            continue

        # Skip words already handled as special patterns
        if word in special_tokens:
            continue

        # CJK text: use jieba tokenization
        if re.search(r"[\u4e00-\u9fff]", word):
            chinese_tokens = tokenizer.tokenize(word, mode="search", enable_english_enhancement=False)
            tokens.extend(chinese_tokens)
        else:
            # Check for version number pattern
            if re.match(r"\d+\.\d+(?:\.\d+)*", word):
                version_tokens = extract_version_tokens(word)
                tokens.extend(version_tokens)
            # Check for camelCase
            elif re.match(r"[A-Z][a-z]+(?:[A-Z][a-z]*)+", word):
                camel_tokens = split_camelcase(word)
                tokens.extend(camel_tokens)
            else:
                # Regular English word: use unified tokenizer service
                if enable_english_enhancement:
                    enhanced_tokens = tokenizer.tokenize(word, mode="simple", enable_english_enhancement=True)
                    tokens.extend(enhanced_tokens)
                else:
                    tokens.append(word)

    # 5. Deduplicate and filter empty values
    result = []
    seen = set()
    for token in tokens:
        if token and token not in seen and len(token.strip()) > 0:
            result.append(token)
            seen.add(token)

    return result


class BM25Retriever:
    """BM25 retriever: keyword retrieval over a document set.

    Core strengths:
    - Pre-built index supporting multiple queries
    - Auto-filters empty documents
    - Smart CJK/English hybrid tokenization
    - Optional English enhancement (stemming + stopword filtering)
    """

    def __init__(self, documents: list[str], enable_english_enhancement: bool = False):
        """Initialize the BM25 retriever.

        Args:
            documents: List of documents, each a string
            enable_english_enhancement: Enable English enhancement (default off to avoid overhead)
        """
        self.documents = documents
        self.enable_english_enhancement = enable_english_enhancement
        self.processed_docs = [
            preprocess_text(doc, enable_english_enhancement=enable_english_enhancement) for doc in documents
        ]

        # Filter empty documents
        valid_indices = [i for i, doc in enumerate(self.processed_docs) if doc]
        self.valid_indices = valid_indices
        self.valid_processed_docs = [self.processed_docs[i] for i in valid_indices]

        logger.debug(
            f"BM25 index init: raw docs={len(documents)}, valid docs={len(valid_indices)}, "
            f"sample tokens={self.processed_docs[0][:10] if self.processed_docs else 'none'}"
        )

        if not self.valid_processed_docs:
            logger.debug("No valid documents for BM25 index")
            self.bm25 = None
        else:
            self.bm25 = BM25Okapi(self.valid_processed_docs)

    def search(self, query: str, top_k: int = 20, only_relevant: bool = False) -> list[tuple[int, float]]:
        """Search for relevant documents using BM25.

        Args:
            query: Query string
            top_k: Number of top results to return
            only_relevant: Only return relevant documents (score > 0), default False

        Returns:
            List of (document_index, BM25_score) sorted by score descending
        """
        total_start_time = time.perf_counter()

        if not self.bm25 or not query.strip():
            logger.debug(f"BM25 search skipped: bm25={self.bm25 is not None}, query='{query.strip()}'")
            return []

        # Preprocess query (using same enhancement settings as documents)
        preprocess_start_time = time.perf_counter()
        processed_query = preprocess_text(query, enable_english_enhancement=self.enable_english_enhancement)
        preprocess_time = time.perf_counter() - preprocess_start_time

        if not processed_query:
            logger.debug(f"BM25 search: query is empty after preprocessing, original='{query}'")
            return []

        logger.debug(
            f"BM25 search start: query='{query}', preprocessed='{' '.join(processed_query)}', "
            f"top_k={top_k}, preprocess={preprocess_time * 1000:.2f}ms"
        )

        # Get BM25 scores
        scoring_start_time = time.perf_counter()
        scores = self.bm25.get_scores(processed_query)
        scoring_time = time.perf_counter() - scoring_start_time

        # Create (original_index, score) pairs
        scoring_docs_start_time = time.perf_counter()
        scored_docs = [(self.valid_indices[i], scores[i]) for i in range(len(scores))]
        scoring_docs_time = time.perf_counter() - scoring_docs_start_time

        # Sort by score descending
        sort_start_time = time.perf_counter()
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        sort_time = time.perf_counter() - sort_start_time

        # Take top-k results
        result = scored_docs[:top_k]

        # Optional: filter non-relevant documents
        if only_relevant:
            result = [(idx, score) for idx, score in result if score > 0]

        total_time = time.perf_counter() - total_start_time

        logger.debug(
            f"BM25 search done: {len(result)} results | "
            f"total={total_time * 1000:.2f}ms "
            f"(preprocess={preprocess_time * 1000:.2f}ms, "
            f"scoring={scoring_time * 1000:.2f}ms, "
            f"build_results={scoring_docs_time * 1000:.2f}ms, "
            f"sort={sort_time * 1000:.2f}ms)"
        )

        return result


def bm25_retrieval(
    documents: list[str], query: str, top_k: int = 20, only_relevant: bool = False
) -> list[tuple[int, float]]:
    """Perform BM25 retrieval over a document set (one-shot interface for single-query scenarios).

    Convenience wrapper around BM25Retriever for simple single-query use cases.

    Args:
        documents: Document list
        query: Query string
        top_k: Number of top results to return
        only_relevant: Only return relevant documents (score > 0), default False

    Returns:
        List of (document_index, BM25_score) sorted by score descending
    """
    return BM25Retriever(documents).search(query, top_k, only_relevant=only_relevant)
