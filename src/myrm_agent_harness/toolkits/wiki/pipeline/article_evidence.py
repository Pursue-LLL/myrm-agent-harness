"""The source text a concept's article is written from, selected within a budget.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: the compile model whose context window bounds the budget)
- toolkits.llms.utils.model_utils::get_model_context_limit (POS: best-effort context window of a model)
- ..core.structure::WikiStructure (POS: raw file resolution inside the vault)
- ..core.types::ConceptInfo (POS: the concept, its definition and the sources it came from)
- ..retrieval.tokenizer::extract_query_terms (POS: EN + CJK term set of a text)

[OUTPUT]
- source_budget_chars: how many characters of source text one article prompt may carry
- build_source_evidence: the line-numbered text of a concept's sources, for the article template's source slot

[POS]
Gives the article stage the text it has to quote and cite. A source that fits its share of the budget is sent whole;
a longer one is cut to its head plus the lines that share the most terms with the concept's name and definition,
each with its neighbours. The selection is deterministic, so a retried article sends the same prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.toolkits.llms.utils.model_utils import get_model_context_limit
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.retrieval.tokenizer import extract_query_terms
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

# The source text may take a quarter of the model's window, a character counted as a token (the worst case, CJK text);
# the rest is for the template, an existing article and the answer.
_WINDOW_DIVISOR = 4
# A document's head (title, abstract, table of contents) gets an eighth of its share even when no line matches.
_HEAD_DIVISOR = 8
# No single line may take more than a quarter of the budget, so one minified line cannot starve the rest.
_LINE_DIVISOR = 4
_WINDOW_RADIUS = 3
_GAP_MARKER = "..."
# A kept line costs its newline and the gap marker it may need in front of it.
_LINE_OVERHEAD = len(_GAP_MARKER) + 2
_ELLIPSIS = "…"


@dataclass(frozen=True, slots=True)
class _SourceText:
    ref: str
    plain: list[str]
    numbered: list[str]

    @property
    def size(self) -> int:
        return sum(len(line) + 1 for line in self.numbered)


def source_budget_chars(llm: BaseChatModel, configured: int) -> int:
    """The configured cap, lowered to a quarter of the model's context window when that is known and smaller."""
    window = get_model_context_limit(llm)
    return configured if window is None else min(configured, window // _WINDOW_DIVISOR)


def build_source_evidence(structure: WikiStructure, concept: ConceptInfo, budget: int) -> str:
    """The sources of ``concept`` as ``### <path>`` blocks of ``<line number>| <text>`` lines.

    Line numbers are those of ``str.splitlines`` on the file, the rule the claims contract slices evidence ranges
    by, so a range the model cites points at the same lines when the claim is pinned. A source that is missing,
    unreadable or out of the vault is listed by its path only. ``budget`` bounds the text lines of all sources
    together; the path headers are not counted.
    """
    max_line = budget // _LINE_DIVISOR
    sources = [_load_source(structure, ref, max_line) for ref in sorted(set(concept.source_files))]
    terms = frozenset(term for term in extract_query_terms(f"{concept.name} {concept.definition}") if len(term) >= 2)
    blocks: list[str] = []
    for source, share in zip(sources, _shares([s.size for s in sources], budget), strict=True):
        body = _excerpt(source, terms, share)
        blocks.append(f"### {source.ref}\n{body}" if body else f"### {source.ref}")
    return "\n\n".join(blocks)


def _load_source(structure: WikiStructure, ref: str, max_line: int) -> _SourceText:
    # ``concept.source_files`` holds vault-relative paths (``raw/x.md``) and ``get_raw_file_path`` wants a raw-relative
    # name, the same normalisation the provenance restore applies to these refs.
    cleaned = ref.strip().replace("\\", "/").removeprefix("raw/")
    text = ""
    if cleaned:
        try:
            text = structure.get_raw_file_path(cleaned).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            logger.warning("Source %s is not available to the article stage: %s", ref, exc)
    plain = [_clip(line, max_line) for line in text.splitlines()]
    return _SourceText(ref, plain, [f"{number}| {line}" for number, line in enumerate(plain, 1)])


def _clip(line: str, limit: int) -> str:
    return line if len(line) <= limit else line[:limit] + _ELLIPSIS


def _shares(sizes: list[int], budget: int) -> list[int]:
    """Split the budget over the sources: the smallest take what they need and the larger ones share the rest."""
    shares = [0] * len(sizes)
    remaining = budget
    for rank, index in enumerate(sorted(range(len(sizes)), key=sizes.__getitem__)):
        shares[index] = min(sizes[index], remaining // (len(sizes) - rank))
        remaining -= shares[index]
    return shares


def _excerpt(source: _SourceText, terms: frozenset[str], budget: int) -> str:
    if budget <= 0:
        return ""
    if source.size <= budget:
        return "\n".join(source.numbered)
    kept = _pick_lines(source, terms, budget)
    rendered: list[str] = []
    previous = -2
    for index in sorted(kept):
        if rendered and index != previous + 1:
            rendered.append(_GAP_MARKER)
        rendered.append(source.numbered[index])
        previous = index
    return "\n".join(rendered)


def _pick_lines(source: _SourceText, terms: frozenset[str], budget: int) -> set[int]:
    kept: set[int] = set()
    used = 0

    def take(index: int, limit: int) -> bool:
        nonlocal used
        cost = len(source.numbered[index]) + _LINE_OVERHEAD
        if used + cost > limit:
            return False
        kept.add(index)
        used += cost
        return True

    for index in range(len(source.numbered)):
        if not take(index, budget // _HEAD_DIVISOR):
            break

    scores = [sum(1 for term in terms if term in line.lower()) for line in source.plain]
    # A line that matches one term only is noise once some line matches two.
    floor = 2 if max(scores, default=0) >= 2 else 1
    hits = sorted((index for index, score in enumerate(scores) if score >= floor), key=lambda i: (-scores[i], i))
    for hit in hits:
        for index in range(max(0, hit - _WINDOW_RADIUS), min(len(source.numbered), hit + _WINDOW_RADIUS + 1)):
            if index not in kept and not take(index, budget):
                break
    return kept
