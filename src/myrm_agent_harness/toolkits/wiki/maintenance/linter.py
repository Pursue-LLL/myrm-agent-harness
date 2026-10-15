"""Wiki linter - Health checks and maintenance.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- ..core.config::WikiConfig (POS: Wiki configuration center)
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- ..core.types::LintIssue, LintResult (POS: Wiki toolkit type definition center)
- .gap_issues::knowledge_gap_issues (POS: knowledge-gap lint issues from graph insights)
- .backlink_discovery::BacklinkDiscoveryMixin (POS: LLM wikilink enrichment of articles)
- .drift_review::DriftReviewMixin (POS: LLM fact-check of sampled articles against their sources)
- .progress::MaintainProgressCallback (POS: observer of how far the LLM phases are)

[OUTPUT]
- WikiLinter: Wiki health check and maintenance engine

[POS]
Wiki health maintenance core engine. Performs wiki quality checks and targeted repairs:
broken link detection, completeness checks (report-only; no LLM auto-write), stale/drift detection, knowledge-gap analysis, and cross-reference discovery.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel

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
from myrm_agent_harness.toolkits.wiki.maintenance.backlink_discovery import BacklinkDiscoveryMixin
from myrm_agent_harness.toolkits.wiki.maintenance.drift_review import DriftReviewMixin
from myrm_agent_harness.toolkits.wiki.maintenance.gap_issues import knowledge_gap_issues
from myrm_agent_harness.toolkits.wiki.maintenance.issue_kind import (
    action_kind_for_issue_type,
)
from myrm_agent_harness.toolkits.wiki.maintenance.modes import MaintainMode
from myrm_agent_harness.toolkits.wiki.maintenance.progress import (
    MaintainProgressCallback,
)
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map import (
    WikiCognitiveMapService,
    WikiMapEvent,
    WikiMapEventType,
)
from myrm_agent_harness.toolkits.wiki.pipeline.publication import (
    publish_concept_article,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_search.providers.web_searcher import WebSearcher
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)


class WikiLinter(BacklinkDiscoveryMixin, DriftReviewMixin):
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
        on_progress: MaintainProgressCallback | None = None,
    ) -> tuple[list[LintIssue], dict[str, object]]:
        """Scan vault health without auto-fix or LLM backlink discovery.

        When ``include_raw_security`` is True (maintain job only), existing raw files
        may be redacted or removed by the raw security gate. ``on_progress`` follows the
        LLM drift review of FULL mode.
        """
        all_issues: list[LintIssue] = []
        raw_scan: dict[str, object] = {}

        all_issues.extend(await self._check_broken_links())
        all_issues.extend(await self._check_completeness())
        all_issues.extend(await self._check_frontmatter_types())
        all_issues.extend(await self._check_provenance_gaps())
        all_issues.extend(await self._check_stale())

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
                                action_kind=action_kind_for_issue_type("security_redacted"),
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
                                action_kind=action_kind_for_issue_type("security_removed"),
                                can_auto_fix=False,
                            )
                        )

        if mode == MaintainMode.FULL and self._config.enable_auto_maintenance:
            drift = await self._check_drift(on_progress)
            all_issues.extend(drift)

        if self._indexer:
            try:
                all_issues.extend(knowledge_gap_issues(self._structure, self._indexer.graph_insights()))
            except Exception as e:
                logger.warning(f"Graph gap analysis failed: {e}")

        return all_issues, raw_scan

    async def lint_and_maintain(
        self,
        mode: MaintainMode = MaintainMode.FULL,
        *,
        on_progress: MaintainProgressCallback | None = None,
    ) -> LintResult:
        """
        Run health check and automatic maintenance.

        Args:
            mode: STRUCTURAL skips LLM drift/backlink discovery; FULL runs the complete pipeline.
            on_progress: told how far the LLM drift review and link discovery are (FULL only).

        Returns:
            LintResult with issues and fixes
        """
        start_time = datetime.now(UTC)
        logger.info("Starting wiki maintenance")

        all_issues, raw_scan = await self.scan(mode, include_raw_security=True, on_progress=on_progress)

        fixed_count = await self._apply_deterministic_fixes(all_issues)

        # Discover new connections
        connections_count = 0
        if mode == MaintainMode.FULL and self._config.enable_backlinks:
            connections_count = await self._discover_connections(on_progress)

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
        raw_security_removed = int(removed_count) if isinstance(removed_count, int) else 0
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
            rel = str(article_path.relative_to(self._structure.concepts_dir).with_suffix("")).replace("\\", "/")
            repair_file_frontmatter(article_path, is_raw_import=False, relative_path=rel)
            logger.info("Repaired frontmatter type for %s", article_path.name)
            content = article_path.read_text(encoding="utf-8")
            await publish_concept_article(self._structure, self._indexer, rel, content)
            return

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
