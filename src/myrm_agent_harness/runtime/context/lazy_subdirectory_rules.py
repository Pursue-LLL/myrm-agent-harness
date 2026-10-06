"""Lazy-loaded subdirectory rules discovery probe and dynamic tool injection hub."""

from __future__ import annotations

import os
from pathlib import Path
from threading import RLock

from myrm_agent_harness.runtime.context.lazy_subdirectory_rules_types import (
    DiscoveredSubdirectoryRule,
    DynamicToolInjectionEnvelope,
    SubdirectoryRuleDiscoveryMode,
)


class LazySubdirectoryRulesProbe:
    """Discovers localized rules in subdirectories on-demand when files or paths are accessed."""

    DEFAULT_CANDIDATE_FILENAMES: tuple[str, ...] = (
        "AGENTS.md",
        "rules.md",
        ".goosehints",
        ".traerules",
    )

    @classmethod
    def find_rules_for_path(
        cls,
        workspace_root: str | Path,
        target_path: str | Path,
        candidate_filenames: tuple[str, ...] | None = None,
    ) -> list[DiscoveredSubdirectoryRule]:
        """Ascends from target path directory up to (but excluding) workspace root looking for rules."""
        ws_root = Path(workspace_root).resolve()
        target = Path(target_path).resolve()
        candidates = candidate_filenames or cls.DEFAULT_CANDIDATE_FILENAMES

        # Prevent directory traversal attacks outside of workspace
        try:
            target.relative_to(ws_root)
        except ValueError:
            return []

        search_dir = target if target.is_dir() else target.parent
        discovered: list[DiscoveredSubdirectoryRule] = []

        curr = search_dir
        while curr != ws_root and curr != curr.parent:
            # Check for candidate rule files within this subdirectory
            for fname in candidates:
                candidate_file = curr / fname
                if candidate_file.is_file():
                    try:
                        content = candidate_file.read_text(encoding="utf-8").strip()
                        if content:
                            rel_dir = str(curr.relative_to(ws_root))
                            discovered.append(
                                DiscoveredSubdirectoryRule(
                                    rule_path=str(candidate_file),
                                    directory_scope=rel_dir,
                                    rule_content=content,
                                )
                            )
                    except (OSError, UnicodeDecodeError):
                        continue

            curr = curr.parent

        # Order from closest directory outwards
        return discovered


class DynamicToolInjectionHub:
    """Intercepts tool output and injects on-demand discovered subdirectory rules."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._seen_rules_per_session: dict[str, set[str]] = {}

    def augment_tool_result(
        self,
        session_id: str,
        workspace_root: str | Path,
        target_path: str | Path,
        raw_tool_output: str,
        mode: SubdirectoryRuleDiscoveryMode = SubdirectoryRuleDiscoveryMode.ON_FIRST_ACCESS,
        candidate_filenames: tuple[str, ...] | None = None,
    ) -> DynamicToolInjectionEnvelope:
        """Discovers localized rules and augments raw tool execution results dynamically."""
        rules = LazySubdirectoryRulesProbe.find_rules_for_path(
            workspace_root=workspace_root,
            target_path=target_path,
            candidate_filenames=candidate_filenames,
        )

        if not rules:
            return DynamicToolInjectionEnvelope(
                original_tool_output=raw_tool_output,
                augmented_tool_output=raw_tool_output,
                injected_rules=(),
                was_injected=False,
                directory_matched="",
            )

        with self._lock:
            seen_set = self._seen_rules_per_session.setdefault(session_id, set())
            rules_to_inject: list[DiscoveredSubdirectoryRule] = []

            for r in rules:
                if mode == SubdirectoryRuleDiscoveryMode.ALWAYS_ATTACH:
                    rules_to_inject.append(r)
                elif (
                    mode == SubdirectoryRuleDiscoveryMode.ON_FIRST_ACCESS
                    and r.sha256_hash not in seen_set
                ):
                    rules_to_inject.append(r)
                    seen_set.add(r.sha256_hash)

        if not rules_to_inject:
            return DynamicToolInjectionEnvelope(
                original_tool_output=raw_tool_output,
                augmented_tool_output=raw_tool_output,
                injected_rules=(),
                was_injected=False,
                directory_matched=rules[0].directory_scope,
            )

        # Assemble formatted rule blocks appended to tool output
        blocks: list[str] = [raw_tool_output.rstrip()]
        for r in rules_to_inject:
            header = f"\n\n---\n[Subdirectory Context Rules: {r.directory_scope} ({os.path.basename(r.rule_path)})]"
            blocks.append(f"{header}\n{r.rule_content}\n---")

        augmented = "".join(blocks)
        matched_scope = rules_to_inject[0].directory_scope

        return DynamicToolInjectionEnvelope(
            original_tool_output=raw_tool_output,
            augmented_tool_output=augmented,
            injected_rules=tuple(rules_to_inject),
            was_injected=True,
            directory_matched=matched_scope,
        )

    def clear_session_cache(self, session_id: str) -> None:
        """Clears the seen rules cache for a specific session."""
        with self._lock:
            self._seen_rules_per_session.pop(session_id, None)
