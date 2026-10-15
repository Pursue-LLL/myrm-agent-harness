"""Knowledge drift review: wiki articles against the raw sources they cite.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- ..core.types::LintIssue (POS: Wiki toolkit type definition center)
- .ai_calls::AiCalls, MaintainStoppedError (POS: the run's model calls: counted, and ended when the host stops the run)
- .issue_kind::action_kind_for_issue_type (POS: issue type to UI action lane)
- .progress::MaintainPhase, MaintainProgressCallback, report_progress (POS: observer of how far the LLM phases are)
- utils.chat_utils::extract_answer_text (POS: LLM 响应答案提取)

[OUTPUT]
- DriftReviewMixin: `_check_drift` for WikiLinter, which asks the LLM to fact-check sampled articles against their sources

[POS]
LLM fact-checking of compiled articles, kept apart from WikiLinter's deterministic health checks.
Samples up to 5 articles per run and reports concrete discrepancies as `drift` issues.
"""

from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.wiki.core.types import LintIssue
from myrm_agent_harness.toolkits.wiki.maintenance.ai_calls import AiCalls, MaintainStoppedError
from myrm_agent_harness.toolkits.wiki.maintenance.issue_kind import action_kind_for_issue_type
from myrm_agent_harness.toolkits.wiki.maintenance.progress import (
    MaintainPhase,
    MaintainProgressCallback,
    report_progress,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

logger = get_agent_logger(__name__)


class DriftReviewMixin:
    """LLM drift review for WikiLinter.

    Expects the host class to provide: _llm, _structure.
    """

    _llm: BaseChatModel
    _structure: WikiStructure

    async def _check_drift(
        self,
        on_progress: MaintainProgressCallback | None = None,
        ai_calls: AiCalls | None = None,
    ) -> list[LintIssue]:
        """
        Detect knowledge drift: wiki articles diverging from raw source facts.

        Samples wiki articles, extracts their claimed sources from frontmatter,
        then uses LLM to compare key facts between wiki and raw source.
        ``on_progress`` is told how many sampled pages are done, before each page and once at the end;
        ``ai_calls`` counts the model calls made; the review ends there when the host stops the run.
        """
        calls = ai_calls if ai_calls is not None else AiCalls()
        issues: list[LintIssue] = []
        concepts = self._structure.list_concepts()

        if not concepts:
            return issues

        sample_size = min(5, len(concepts))
        sample = random.sample(concepts, sample_size)

        for done, concept_path in enumerate(sample):
            report_progress(on_progress, MaintainPhase.DRIFT_REVIEW, done, sample_size)
            try:
                wiki_content = concept_path.read_text(encoding="utf-8")

                # Extract sources from frontmatter
                sources = self._extract_frontmatter_sources(wiki_content)
                if not sources:
                    continue

                # Load raw source content for comparison
                raw_excerpts: list[str] = []
                for src in sources[:3]:
                    raw_path = self._structure.raw_dir / src
                    if raw_path.exists():
                        raw_text = raw_path.read_text(encoding="utf-8")
                        raw_excerpts.append(f"--- {src} ---\n{raw_text[:2000]}")

                if not raw_excerpts:
                    continue

                system_msg = SystemMessage(
                    content=(
                        "You are a fact-checking expert. Compare the wiki article with its raw sources. "
                        "Report ONLY concrete factual discrepancies: wrong numbers, missing conditions, "
                        "paraphrased data that lost precision. "
                        "If everything is accurate, respond with exactly: NO_DRIFT"
                    )
                )
                human_msg = HumanMessage(
                    content=(
                        f"## Wiki Article ({concept_path.stem}):\n{wiki_content[:2000]}\n\n"
                        f"## Raw Sources:\n{''.join(raw_excerpts)}"
                    )
                )

                response = await calls.ask(self._llm, [system_msg, human_msg])
                # 兼容 Anthropic 块列表 / reasoning 模型 content 空回退
                response_text = extract_answer_text(response).strip()

                if "NO_DRIFT" not in response_text:
                    issues.append(
                        LintIssue(
                            issue_type="drift",
                            severity="high",
                            location=str(concept_path),
                            description=response_text[:300],
                            action_kind=action_kind_for_issue_type("drift"),
                            can_auto_fix=False,
                            suggested_fix="Review and recompile this article from raw sources",
                        )
                    )

            except MaintainStoppedError:
                break
            except Exception as e:
                logger.warning(f"Drift check failed for {concept_path}: {e}")
        report_progress(on_progress, MaintainPhase.DRIFT_REVIEW, sample_size, sample_size)

        return issues

    @staticmethod
    def _extract_frontmatter_sources(content: str) -> list[str]:
        """Extract source file paths from YAML frontmatter 'sources' field."""
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not frontmatter_match:
            return []

        frontmatter = frontmatter_match.group(1)
        sources: list[str] = []
        in_sources = False
        for line in frontmatter.split("\n"):
            stripped = line.strip()
            if stripped.startswith("sources:"):
                in_sources = True
                continue
            if in_sources:
                if stripped.startswith("- "):
                    sources.append(stripped[2:].strip().strip("'\""))
                elif stripped and not stripped.startswith(" "):
                    break
        return sources
