"""Wiki linter - Health checks and maintenance.

[INPUT]
langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
..core.config::WikiConfig (POS: Wiki configuration center)
..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
..core.types::LintIssue, LintResult (POS: Wiki toolkit type definition center)
utils.chat_utils::extract_answer_text (POS: LLM 响应答案提取 — 兼容 reasoning 模型 content 空回退)

[OUTPUT]
WikiLinter: Wiki health check and maintenance engine

[POS]
Wiki health maintenance core engine. Performs wiki quality checks and targeted repairs:
broken link detection, completeness checks (report-only; no LLM auto-write), stale/drift detection, knowledge-gap analysis, and cross-reference discovery.
"""

from __future__ import annotations

import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    repair_file_frontmatter,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import LintIssue, LintResult
from myrm_agent_harness.toolkits.wiki.diagnostics.structural_lint import (
    collect_broken_link_issues,
    collect_broken_wikilink_issues,
    collect_invalid_frontmatter_type_issues,
    collect_provenance_gap_issues,
)
from myrm_agent_harness.toolkits.wiki.maintenance.issue_kind import (
    action_kind_for_issue_type,
)
from myrm_agent_harness.toolkits.wiki.maintenance.modes import MaintainMode
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map import (
    WikiCognitiveMapService,
    WikiMapEvent,
    WikiMapEventType,
)
from myrm_agent_harness.toolkits.wiki.pipeline.publication import (
    publish_concept_article,
)
from myrm_agent_harness.utils.chat_utils import extract_answer_text
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_search.web_searcher import WebSearcher
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)


class WikiLinter:
    """Wiki health checker and automatic maintenance engine.

    Checks: broken links, completeness, stale content, drift,
    knowledge-gap analysis (isolated/bridge nodes). Auto-repairs and discovers connections.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        structure: WikiStructure,
        config: WikiConfig,
        indexer: WikiIndexer | None = None,
        web_searcher: WebSearcher | None = None,
    ):
        self._llm = llm
        self._structure = structure
        self._config = config
        self._indexer = indexer
        self._web_searcher = web_searcher

    async def scan(
        self,
        mode: MaintainMode = MaintainMode.STRUCTURAL,
        *,
        include_raw_security: bool = False,
    ) -> tuple[list[LintIssue], dict[str, object]]:
        """Scan vault health without auto-fix or LLM backlink discovery.

        When ``include_raw_security`` is True (maintain job only), existing raw files
        may be redacted or removed by the raw security gate.
        """
        all_issues: list[LintIssue] = []
        raw_scan: dict[str, object] = {}

        broken_links = await self._check_broken_links()
        all_issues.extend(broken_links)

        incomplete = await self._check_completeness()
        all_issues.extend(incomplete)

        invalid_types = await self._check_frontmatter_types()
        all_issues.extend(invalid_types)

        provenance_gaps = await self._check_provenance_gaps()
        all_issues.extend(provenance_gaps)

        stale = await self._check_stale()
        all_issues.extend(stale)

        if include_raw_security:
            from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate import (
                scan_existing_raw_vault,
            )

            raw_scan = await scan_existing_raw_vault(self._structure, self._indexer)
            redacted_paths = raw_scan.get("redacted_paths", [])
            if isinstance(redacted_paths, list):
                for rel_path in redacted_paths:
                    if isinstance(rel_path, str):
                        all_issues.append(
                            LintIssue(
                                issue_type="security_redacted",
                                severity="medium",
                                location=rel_path,
                                description="Sensitive content redacted in raw source",
                                action_kind=action_kind_for_issue_type(
                                    "security_redacted"
                                ),
                                can_auto_fix=False,
                            )
                        )
            removed_paths = raw_scan.get("removed_paths", [])
            if isinstance(removed_paths, list):
                for rel_path in removed_paths:
                    if isinstance(rel_path, str):
                        all_issues.append(
                            LintIssue(
                                issue_type="security_removed",
                                severity="high",
                                location=rel_path,
                                description="Blocked raw source removed during maintenance",
                                action_kind=action_kind_for_issue_type(
                                    "security_removed"
                                ),
                                can_auto_fix=False,
                            )
                        )

        if mode == MaintainMode.FULL and self._config.enable_auto_maintenance:
            drift = await self._check_drift()
            all_issues.extend(drift)

        if self._indexer:
            try:
                insights = self._indexer.graph_insights()
                _gap_desc = {
                    "isolated": lambda g: f"Isolated concept ({g.get('degree', 0)} connections)",
                    "bridge": lambda g: f"Bridge node (connects {g.get('communities_connected', 0)} communities)",
                }
                for gap in insights.get("knowledge_gaps", []):
                    desc_fn = _gap_desc.get(gap.get("type", ""))
                    if desc_fn:
                        all_issues.append(
                            LintIssue(
                                issue_type="knowledge_gap",
                                severity="low",
                                location=str(gap["node"]),
                                description=desc_fn(gap),
                                action_kind=action_kind_for_issue_type("knowledge_gap"),
                            )
                        )
            except Exception as e:
                logger.warning(f"Graph gap analysis failed: {e}")

        return all_issues, raw_scan

    async def lint_and_maintain(
        self, mode: MaintainMode = MaintainMode.FULL
    ) -> LintResult:
        """
        Run health check and automatic maintenance.

        Args:
            mode: STRUCTURAL skips LLM drift/backlink discovery; FULL runs the complete pipeline.

        Returns:
            LintResult with issues and fixes
        """
        start_time = datetime.now(UTC)
        logger.info("Starting wiki maintenance")

        all_issues, raw_scan = await self.scan(mode, include_raw_security=True)

        fixed_count = await self._apply_deterministic_fixes(all_issues)

        # Discover new connections
        connections_count = 0
        if mode == MaintainMode.FULL and self._config.enable_backlinks:
            connections_count = await self._discover_connections()

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

        logger.info(
            f"Maintenance complete: {len(all_issues)} issues found, "
            f"{fixed_count} fixed, {connections_count} connections discovered"
        )

        WikiCognitiveMapService(self._structure).refresh(
            WikiMapEvent(
                event_type=WikiMapEventType.MAINTAIN,
                summary=(
                    f"Maintenance finished: {len(all_issues)} issue(s), "
                    f"{fixed_count} fixed, {connections_count} new connection(s)"
                ),
                details={
                    "issues_found": len(all_issues),
                    "issues_fixed": fixed_count,
                    "connections_discovered": connections_count,
                },
            )
        )

        removed_count = raw_scan.get("files_removed", 0)
        removed_paths_list = raw_scan.get("removed_paths", [])
        raw_security_removed = (
            int(removed_count) if isinstance(removed_count, int) else 0
        )
        raw_security_removed_paths = (
            [str(path) for path in removed_paths_list if isinstance(path, str)]
            if isinstance(removed_paths_list, list)
            else []
        )

        await self._maybe_commit_vault_git("maintain")

        return LintResult(
            issues_found=len(all_issues),
            issues_fixed=fixed_count,
            connections_discovered=connections_count,
            duration_ms=duration_ms,
            issues=all_issues,
            raw_security_removed=raw_security_removed,
            raw_security_removed_paths=raw_security_removed_paths,
        )

    async def _maybe_commit_vault_git(self, reason: str) -> None:
        import asyncio

        from ..portability.vault_git import maybe_commit_vault_git_snapshot

        await asyncio.to_thread(
            maybe_commit_vault_git_snapshot,
            self._structure,
            self._config,
            reason=reason,
        )

    async def _check_broken_links(self) -> list[LintIssue]:
        """Check for broken internal markdown links and wikilinks."""
        return [
            *collect_broken_link_issues(self._structure),
            *collect_broken_wikilink_issues(self._structure),
        ]

    async def _check_completeness(self) -> list[LintIssue]:
        """Check for incomplete articles."""
        issues = []
        concepts = self._structure.list_concepts()

        for concept_path in concepts:
            try:
                content = concept_path.read_text(encoding="utf-8")

                if len(content) < 200:
                    issues.append(
                        LintIssue(
                            issue_type="incomplete",
                            severity="low",
                            location=str(concept_path),
                            description=f"Article too short ({len(content)} chars)",
                            action_kind=action_kind_for_issue_type("incomplete"),
                            can_auto_fix=False,
                            suggested_fix="Enhance article with more details",
                        )
                    )

                if "TODO" in content or "FIXME" in content:
                    issues.append(
                        LintIssue(
                            issue_type="incomplete",
                            severity="medium",
                            location=str(concept_path),
                            description="Contains TODO/FIXME markers",
                            action_kind=action_kind_for_issue_type("incomplete"),
                            can_auto_fix=False,
                        )
                    )

            except Exception as e:
                logger.warning(f"Failed to check completeness of {concept_path}: {e}")

        return issues

    async def _check_frontmatter_types(self) -> list[LintIssue]:
        """Check concept articles for required frontmatter `type` field."""
        return collect_invalid_frontmatter_type_issues(self._structure)

    async def _check_provenance_gaps(self) -> list[LintIssue]:
        """Check concept articles for missing or broken raw source provenance."""
        return collect_provenance_gap_issues(self._structure)

    async def _apply_deterministic_fixes(self, issues: list[LintIssue]) -> int:
        """Apply only deterministic vault repairs (frontmatter type gate)."""
        fixed_count = 0
        for issue in issues:
            if not issue.can_auto_fix:
                continue
            try:
                await self._auto_fix_issue(issue)
                fixed_count += 1
            except Exception as e:
                logger.error(f"Failed to auto-fix {issue.issue_type}: {e}")
        return fixed_count

    async def _auto_fix_issue(self, issue: LintIssue) -> None:
        """Automatically fix an issue if possible."""
        if issue.issue_type == "invalid_frontmatter_type":
            article_path = Path(issue.location)
            if not article_path.exists():
                return
            rel = str(
                article_path.relative_to(self._structure.concepts_dir).with_suffix("")
            ).replace("\\", "/")
            repair_file_frontmatter(
                article_path, is_raw_import=False, relative_path=rel
            )
            logger.info("Repaired frontmatter type for %s", article_path.name)
            content = article_path.read_text(encoding="utf-8")
            await publish_concept_article(self._structure, self._indexer, rel, content)
            return

    async def _discover_connections(self) -> int:
        """
        Discover potential cross-references using LLM-driven link enrichment.

        Uses LLM to identify semantic relationships that simple string matching would miss,
        while avoiding false positives from naive keyword overlap.

        Returns:
            Number of new connections discovered
        """
        concepts = self._structure.list_concepts()
        if len(concepts) < 2:
            return 0

        connections_count = 0
        concept_names = [p.stem.replace("-", " ") for p in concepts]
        concept_index = "\n".join(f"- {name}" for name in concept_names)

        for concept_path in concepts[:20]:
            try:
                content = concept_path.read_text(encoding="utf-8")
                current_name = concept_path.stem.replace("-", " ")

                # Extract existing wikilinks to avoid duplicates
                existing_links = set(re.findall(r"\[\[([^\]]+)\]\]", content))
                existing_links_lower = {
                    link.split("|")[0].strip().lower() for link in existing_links
                }

                system_msg = SystemMessage(
                    content=(
                        "You are a knowledge graph expert. Given a wiki article and a list of other concepts, "
                        "identify which concepts should be linked FROM this article using [[Wikilinks]]. "
                        "Only suggest links where there's a genuine semantic relationship. "
                        'Return ONLY a JSON array of concept names to link, e.g. ["Concept A", "Concept B"]. '
                        "Return [] if no links are needed."
                    )
                )
                human_msg = HumanMessage(
                    content=(
                        f"## Article: {current_name}\n{content[:1500]}\n\n"
                        f"## Available concepts to potentially link:\n{concept_index}\n\n"
                        f"## Already linked: {list(existing_links)}"
                    )
                )

                response = await self._llm.ainvoke([system_msg, human_msg])
                response_text = extract_answer_text(response).strip()

                try:
                    if response_text.startswith("```"):
                        response_text = response_text.split("```")[1]
                        if response_text.startswith("json"):
                            response_text = response_text[4:]
                    suggested = json.loads(response_text)
                except (json.JSONDecodeError, IndexError):
                    continue

                if not isinstance(suggested, list):
                    continue

                # Add new wikilinks
                article_modified = False
                for link_name in suggested:
                    if not isinstance(link_name, str):
                        continue
                    if (
                        link_name.lower() in existing_links_lower
                        or link_name.lower() == current_name.lower()
                    ):
                        continue
                    # Verify concept exists
                    if link_name.lower() not in {n.lower() for n in concept_names}:
                        continue

                    content += f"\n- [[{link_name}]]"
                    article_modified = True
                    connections_count += 1
                    logger.info(f"LLM discovered link: {current_name} -> {link_name}")

                if article_modified:
                    rel = str(
                        concept_path.relative_to(
                            self._structure.concepts_dir
                        ).with_suffix("")
                    ).replace("\\", "/")
                    await publish_concept_article(
                        self._structure, self._indexer, rel, content
                    )

            except Exception as e:
                logger.warning(f"LLM link enrichment failed for {concept_path}: {e}")

        return connections_count

    async def _check_stale(self) -> list[LintIssue]:
        """Detect wiki articles whose source raw files have been modified after compilation."""
        from myrm_agent_harness.toolkits.wiki.maintenance.stale_summary import (
            collect_stale_raw_files,
        )

        summary = collect_stale_raw_files(self._structure)
        return [
            LintIssue(
                issue_type="stale",
                severity="medium",
                location=item.relative_path,
                description="Raw source updated after last compilation",
                action_kind=action_kind_for_issue_type("stale"),
                can_auto_fix=False,
                suggested_fix="Recompile to update wiki from this source",
            )
            for item in summary.stale_files
        ]

    async def _check_drift(self) -> list[LintIssue]:
        """
        Detect knowledge drift: wiki articles diverging from raw source facts.

        Samples wiki articles, extracts their claimed sources from frontmatter,
        then uses LLM to compare key facts between wiki and raw source.
        """
        issues: list[LintIssue] = []
        concepts = self._structure.list_concepts()

        if not concepts:
            return issues

        sample_size = min(5, len(concepts))
        sample = random.sample(concepts, sample_size)

        for concept_path in sample:
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

                response = await self._llm.ainvoke([system_msg, human_msg])
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

            except Exception as e:
                logger.warning(f"Drift check failed for {concept_path}: {e}")

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
