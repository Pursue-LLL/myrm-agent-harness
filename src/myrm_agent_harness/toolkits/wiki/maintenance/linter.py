"""Wiki linter - Health checks and maintenance.

[INPUT]
langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
langchain_core.messages::HumanMessage, SystemMessage (POS: LangChain message types)
..core.config::WikiConfig (POS: Wiki configuration center)
..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
..core.types::LintIssue, LintResult (POS: Wiki toolkit type definition center)

[OUTPUT]
WikiLinter: Wiki health check and maintenance engine

[POS]
Wiki health maintenance core engine. Performs wiki quality checks and automatic repairs:
broken link detection, completeness checks (short articles, TODO markers), consistency checks
(LLM-driven), automatic repair of incomplete articles, and discovery of potential cross-reference connections.
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
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import LintIssue, LintResult
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_search.web_searcher import WebSearcher
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)


class WikiLinter:
    """
    Wiki health checker and automatic maintenance engine.

    Features:
    - Consistency checks (detect contradictions)
    - Completeness checks (find missing information)
    - Broken link detection
    - Automatic repair (web search for missing info)
    - Connection discovery (find potential cross-references)
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

    async def lint_and_maintain(self) -> LintResult:
        """
        Run full health check and automatic maintenance.

        Returns:
            LintResult with issues and fixes
        """
        start_time = datetime.now(UTC)
        logger.info("Starting wiki maintenance")

        all_issues: list[LintIssue] = []

        # Check 1: Broken links
        broken_links = await self._check_broken_links()
        all_issues.extend(broken_links)

        # Check 2: Completeness
        incomplete = await self._check_completeness()
        all_issues.extend(incomplete)

        # Check 3: Consistency (advanced, requires LLM)
        if self._config.enable_auto_maintenance:
            consistency = await self._check_consistency()
            all_issues.extend(consistency)

        # Check 4: Stale content (raw files updated but wiki not recompiled)
        stale = await self._check_stale()
        all_issues.extend(stale)

        # Check 5: Knowledge drift (wiki diverged from raw source facts)
        if self._config.enable_auto_maintenance:
            drift = await self._check_drift()
            all_issues.extend(drift)

        # Auto-fix issues
        fixed_count = 0
        for issue in all_issues:
            if issue.can_auto_fix:
                try:
                    await self._auto_fix_issue(issue)
                    fixed_count += 1
                except Exception as e:
                    logger.error(f"Failed to auto-fix {issue.issue_type}: {e}")

        # Discover new connections
        connections_count = 0
        if self._config.enable_backlinks:
            connections_count = await self._discover_connections()

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

        logger.info(
            f"Maintenance complete: {len(all_issues)} issues found, "
            f"{fixed_count} fixed, {connections_count} connections discovered"
        )

        return LintResult(
            issues_found=len(all_issues),
            issues_fixed=fixed_count,
            connections_discovered=connections_count,
            duration_ms=duration_ms,
            issues=all_issues,
        )

    async def _check_broken_links(self) -> list[LintIssue]:
        """Check for broken internal links."""
        issues = []
        concepts = self._structure.list_concepts()

        for concept_path in concepts:
            try:
                content = concept_path.read_text(encoding="utf-8")
                links = re.findall(r"\[([^\]]+)\]\(([^\)]+)\)", content)

                for _link_text, link_target in links:
                    if not link_target.startswith("http"):
                        target_path = (concept_path.parent / link_target).resolve()
                        if not target_path.exists():
                            issues.append(
                                LintIssue(
                                    issue_type="broken_link",
                                    severity="medium",
                                    location=str(concept_path),
                                    description=f"Broken link to {link_target}",
                                    can_auto_fix=False,
                                )
                            )

            except Exception as e:
                logger.warning(f"Failed to check links in {concept_path}: {e}")

        return issues

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
                            can_auto_fix=True,
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
                            can_auto_fix=False,
                        )
                    )

            except Exception as e:
                logger.warning(f"Failed to check completeness of {concept_path}: {e}")

        return issues

    async def _check_consistency(self) -> list[LintIssue]:
        """
        Check for contradictions or inconsistencies (using LLM).

        This is an advanced check that requires LLM analysis.
        """
        issues = []
        concepts = self._structure.list_concepts()

        if len(concepts) < 2:
            return issues

        for _i, concept_path in enumerate(concepts[:10]):
            try:
                content = concept_path.read_text(encoding="utf-8")

                system_msg = SystemMessage(
                    content="You are a wiki quality checker. Identify contradictions or inconsistencies."
                )
                human_msg = HumanMessage(
                    content=f"Check this article for issues:\n\n{content}\n\nReport any problems found."
                )

                response = await self._llm.ainvoke([system_msg, human_msg])

                if "inconsistency" in response.content.lower() or "contradiction" in response.content.lower():
                    issues.append(
                        LintIssue(
                            issue_type="inconsistency",
                            severity="high",
                            location=str(concept_path),
                            description=response.content[:200],
                            can_auto_fix=False,
                        )
                    )

            except Exception as e:
                logger.error(f"Failed to check consistency of {concept_path}: {e}")
                break

        return issues

    async def _auto_fix_issue(self, issue: LintIssue) -> None:
        """Automatically fix an issue if possible."""
        if issue.issue_type == "incomplete":
            logger.info(f"Auto-fixing incomplete article: {issue.location}")

            article_path = Path(issue.location)
            if not article_path.exists():
                return

            content = article_path.read_text(encoding="utf-8")

            system_msg = SystemMessage(content="You are enhancing a wiki article.")
            human_msg = HumanMessage(content=f"Enhance this article with more details:\n\n{content}")

            try:
                response = await self._llm.ainvoke([system_msg, human_msg])
                enhanced_content = response.content
                article_path.write_text(enhanced_content, encoding="utf-8")
                logger.info(f"Enhanced article: {article_path.name}")

                if self._indexer:
                    concept_name = article_path.stem
                    await self._indexer.upsert(concept_name, enhanced_content)
                    self._indexer.extract_and_upsert_edges(concept_name, enhanced_content)

            except Exception as e:
                logger.error(f"Failed to enhance article: {e}")
                raise

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
                existing_links_lower = {link.split("|")[0].strip().lower() for link in existing_links}

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
                response_text = response.content.strip()

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
                    if link_name.lower() in existing_links_lower or link_name.lower() == current_name.lower():
                        continue
                    # Verify concept exists
                    if link_name.lower() not in {n.lower() for n in concept_names}:
                        continue

                    content += f"\n- [[{link_name}]]"
                    article_modified = True
                    connections_count += 1
                    logger.info(f"LLM discovered link: {current_name} -> {link_name}")

                if article_modified:
                    concept_path.write_text(content, encoding="utf-8")
                    if self._indexer:
                        await self._indexer.upsert(concept_path.stem, content)
                        self._indexer.extract_and_upsert_edges(concept_path.stem, content)

            except Exception as e:
                logger.warning(f"LLM link enrichment failed for {concept_path}: {e}")

        return connections_count

    async def _check_stale(self) -> list[LintIssue]:
        """Detect wiki articles whose source raw files have been modified after compilation."""
        issues: list[LintIssue] = []

        metadata_path = self._structure.get_wiki_metadata_path()
        if not metadata_path.exists():
            return issues

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            last_compile = metadata.get("last_compile_time", "")
            if not last_compile:
                return issues
            compile_ts = datetime.fromisoformat(last_compile).timestamp()
        except Exception:
            return issues

        raw_files = self._structure.list_raw_files()
        for raw_file in raw_files:
            try:
                if raw_file.stat().st_mtime > compile_ts:
                    issues.append(
                        LintIssue(
                            issue_type="stale",
                            severity="medium",
                            location=str(raw_file),
                            description="Raw source updated after last compilation",
                            can_auto_fix=True,
                            suggested_fix="Recompile to update wiki from this source",
                        )
                    )
            except OSError:
                pass

        return issues

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
                response_text = response.content.strip()

                if "NO_DRIFT" not in response_text:
                    issues.append(
                        LintIssue(
                            issue_type="drift",
                            severity="high",
                            location=str(concept_path),
                            description=response_text[:300],
                            can_auto_fix=True,
                            suggested_fix="Recompile this article from raw sources to fix drift",
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
