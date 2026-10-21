"""Subagent Workspace Context Inheritance & Prompt Enrichment Engine (Item 56).

Implements workspace context discovery along the priority chain (.rules > AGENTS.md > README.md),
context token budget capping with differential compact summarization, role-adaptive prompt
enrichment, and immutable inheritance audit tracking.

[INPUT]
- __future__
- os
- re
- time
- uuid
- pathlib

[OUTPUT]
- SubagentWorkspaceContextEnricher

[POS]
Subagent Workspace Context Inheritance & Prompt Enrichment Engine (Item 56).
"""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path

from .types import (
    ContextRuleSnippet,
    ContextSourceType,
    EnrichmentResult,
    InheritanceAuditRecord,
    RulePriority,
    SubagentRole,
    WorkspaceInheritanceConfig,
)


class SubagentWorkspaceContextEnricher:
    """Enriches subagent system prompts with inherited parent workspace context."""

    def __init__(self, config: WorkspaceInheritanceConfig | None = None) -> None:
        self.config = config or WorkspaceInheritanceConfig()
        self._audit_log: list[InheritanceAuditRecord] = []

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count based on standard 4-char per token heuristic."""
        return max(1, len(text.strip()) // 4)

    def _determine_priority(self, title: str, content: str) -> RulePriority:
        """Categorize rule importance into critical, high, normal, or low priority."""
        lowered = f"{title} {content}".lower()
        if any(w in lowered for w in ["redline", "security", "never", "forbidden", "fail-closed", "no-delete"]):
            return RulePriority.CRITICAL
        if any(w in lowered for w in ["type hint", "convention", "pep8", "eslint", "test", "requirement"]):
            return RulePriority.HIGH
        if any(w in lowered for w in ["guideline", "workflow", "git", "pull request", "commit", "pattern"]):
            return RulePriority.NORMAL
        return RulePriority.LOW

    def discover_context_snippets(self, workspace_root: str | Path) -> list[ContextRuleSnippet]:
        """Discover and parse workspace rules following the priority chain."""
        root_path = Path(workspace_root)
        snippets: list[ContextRuleSnippet] = []

        for source in self.config.priority_chain:
            target_path = root_path / source.value
            if not target_path.exists() or not target_path.is_file():
                continue

            try:
                content = target_path.read_text(encoding="utf-8")
                # Parse markdown sections or paragraphs
                sections = re.split(r"\n(?=#{1,4}\s+|\b[A-Z0-9_\-]+\s*:)", content)
                for sec in sections:
                    cleaned = sec.strip()
                    if not cleaned or len(cleaned) < 10:
                        continue
                    first_line = cleaned.split("\n")[0].lstrip("#").strip()
                    priority = self._determine_priority(first_line, cleaned)
                    token_cnt = self._estimate_tokens(cleaned)
                    snippets.append(
                        ContextRuleSnippet(
                            source_type=source,
                            file_path=str(target_path),
                            priority=priority,
                            title=first_line[:60],
                            content=cleaned,
                            token_count=token_cnt,
                        )
                    )
            except OSError:
                continue

        # If no physical files were detected (e.g. testing or clean repo), generate baseline invariants
        if not snippets:
            snippets.extend(self._get_fallback_invariants(str(root_path)))

        return snippets

    def _get_fallback_invariants(self, workspace_root: str) -> list[ContextRuleSnippet]:
        """Provide baseline architectural and security invariants when root files are absent."""
        defaults = [
            (
                ContextSourceType.RULES,
                RulePriority.CRITICAL,
                "Absolute Security & Code Integrity",
                "Never execute destructive shell commands (rm -rf, git reset/revert). Maintain fail-closed boundaries.",
            ),
            (
                ContextSourceType.AGENTS_MD,
                RulePriority.HIGH,
                "Type Safety & Clean Architecture",
                "Strict type hints required. Zero Any types permitted. Single responsibility per module with test coverage.",
            ),
            (
                ContextSourceType.README_MD,
                RulePriority.NORMAL,
                "Project Architecture Baseline",
                f"Active workspace root is bound to {workspace_root}. Respect existing directories and module hierarchy.",
            ),
        ]
        return [
            ContextRuleSnippet(
                source_type=src,
                file_path=os.path.join(workspace_root, src.value),
                priority=prio,
                title=title,
                content=text,
                token_count=self._estimate_tokens(text),
            )
            for src, prio, title, text in defaults
        ]

    def prune_snippets_by_budget(
        self,
        snippets: list[ContextRuleSnippet],
        max_tokens: int,
    ) -> tuple[list[ContextRuleSnippet], bool]:
        """Apply token budget capping with priority preservation and differential compacting."""
        # Sort by priority rank: CRITICAL > HIGH > NORMAL > LOW
        priority_order = {
            RulePriority.CRITICAL: 0,
            RulePriority.HIGH: 1,
            RulePriority.NORMAL: 2,
            RulePriority.LOW: 3,
        }
        sorted_snippets = sorted(snippets, key=lambda s: priority_order[s.priority])

        total_tokens = sum(s.token_count for s in sorted_snippets)
        if total_tokens <= max_tokens:
            return sorted_snippets, False

        # Budget exceeded: compact or prune lower-priority items
        compacted_snippets: list[ContextRuleSnippet] = []
        accumulated = 0
        is_compacted = False

        for snippet in sorted_snippets:
            if snippet.priority in (RulePriority.CRITICAL, RulePriority.HIGH):
                if accumulated + snippet.token_count <= max_tokens:
                    compacted_snippets.append(snippet)
                    accumulated += snippet.token_count
                else:
                    # Compact high priority to headline
                    headline = snippet.title
                    comp_tokens = self._estimate_tokens(headline)
                    if accumulated + comp_tokens <= max_tokens:
                        compacted_snippets.append(
                            ContextRuleSnippet(
                                source_type=snippet.source_type,
                                file_path=snippet.file_path,
                                priority=snippet.priority,
                                title=snippet.title,
                                content=f"Constraint: {headline}",
                                token_count=comp_tokens,
                            )
                        )
                        accumulated += comp_tokens
                        is_compacted = True
            elif self.config.enable_compact_summarization:
                # Normal or Low priority: compact summary
                short_summary = snippet.title
                summary_tokens = self._estimate_tokens(short_summary)
                if accumulated + summary_tokens <= max_tokens:
                    compacted_snippets.append(
                        ContextRuleSnippet(
                            source_type=snippet.source_type,
                            file_path=snippet.file_path,
                            priority=snippet.priority,
                            title=snippet.title,
                            content=f"Summary: {short_summary}",
                            token_count=summary_tokens,
                        )
                    )
                    accumulated += summary_tokens
                    is_compacted = True
                else:
                    is_compacted = True
            else:
                is_compacted = True

        return compacted_snippets, is_compacted

    def enrich_child_system_prompt(
        self,
        base_prompt: str,
        workspace_root: str,
        role: SubagentRole = SubagentRole.WORKER,
    ) -> EnrichmentResult:
        """Enrich subagent base prompt by embedding tailored workspace context rules."""
        raw_snippets = self.discover_context_snippets(workspace_root)

        # Role-based focus prioritization
        if role == SubagentRole.REVIEWER:
            focused = [s for s in raw_snippets if s.priority in (RulePriority.CRITICAL, RulePriority.HIGH)]
        elif role == SubagentRole.WORKER:
            focused = raw_snippets
        else:
            focused = raw_snippets

        pruned_snippets, is_compacted = self.prune_snippets_by_budget(
            focused,
            self.config.max_context_tokens,
        )

        injected_token_count = sum(s.token_count for s in pruned_snippets)
        matched_sources = sorted({s.source_type.value for s in pruned_snippets})

        # Assemble markdown context injection block
        lines = [
            "\n\n<!-- INHERITED WORKSPACE CONTEXT (Item 56) -->",
            f"### Inherited Workspace Rules & Invariants (Workspace: `{workspace_root}`, Role: `{role.value}`)",
        ]
        if is_compacted:
            lines.append("> [!NOTE] Workspace rules compacted under context budget limit.")

        for snippet in pruned_snippets:
            lines.append(f"- **[{snippet.source_type.value} | {snippet.priority.value.upper()}]** {snippet.content}")

        lines.append("<!-- END INHERITED CONTEXT -->\n")
        context_block = "\n".join(lines)

        enriched_prompt = base_prompt + context_block

        # Record audit log
        audit = InheritanceAuditRecord(
            audit_id=f"audit-{uuid.uuid4().hex[:8]}",
            workspace_root=workspace_root,
            subagent_role=role,
            injected_tokens=injected_token_count,
            compacted=is_compacted,
            timestamp=time.time(),
            matched_files=matched_sources,
        )
        self._audit_log.append(audit)
        if len(self._audit_log) > 50:
            self._audit_log = self._audit_log[-50:]

        return EnrichmentResult(
            original_prompt=base_prompt,
            enriched_prompt=enriched_prompt,
            injected_token_count=injected_token_count,
            is_compacted=is_compacted,
            matched_sources=matched_sources,
            applied_snippets=pruned_snippets,
        )

    def get_audit_history(self) -> list[InheritanceAuditRecord]:
        """Retrieve recent workspace inheritance audit records."""
        return list(self._audit_log)
