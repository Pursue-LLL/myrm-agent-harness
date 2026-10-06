"""Dual-readable environment changelog and anti-amnesia recovery ledger.

Provides structured auditing for sandbox mutations (packages, MCP tools, env vars),
and generates consolidated state digests for zero-delay cross-session context rehydration.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import UTC, datetime

from myrm_agent_harness.runtime.context.environment_changelog_types import (
    EnvironmentChangelogEntry,
    EnvironmentMutationKind,
    EnvironmentStateDigest,
    MutationActor,
    RehydrationInjectionPayload,
)

logger = logging.getLogger(__name__)


class EnvironmentChangelogLedger:
    """Audits environment mutations and synthesizes anti-amnesia context digests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[EnvironmentChangelogEntry] = []

    def record_mutation(
        self,
        kind: EnvironmentMutationKind,
        target_name: str,
        new_state: str,
        old_state: str | None = None,
        actor: MutationActor = MutationActor.AGENT,
        rationale: str = "",
        is_verified: bool = True,
    ) -> EnvironmentChangelogEntry:
        """Atomically append a structured mutation event to the ledger."""
        entry = EnvironmentChangelogEntry(
            entry_id=f"mut_{uuid.uuid4().hex[:12]}",
            actor=actor,
            kind=kind,
            target_name=target_name,
            old_state=old_state,
            new_state=new_state,
            rationale=rationale,
            is_verified=is_verified,
        )
        with self._lock:
            self._entries.append(entry)
        logger.debug("Recorded environment mutation: %s -> %s", kind, target_name)
        return entry

    def generate_state_digest(self) -> EnvironmentStateDigest:
        """Consolidate linear mutation history into a current state snapshot."""
        with self._lock:
            entries = list(self._entries)

        installed_packages: dict[str, str] = {}
        active_mcp_servers: set[str] = set()
        effective_env_vars: dict[str, str] = {}
        last_timestamp: float | None = None

        for entry in entries:
            last_timestamp = entry.timestamp
            if entry.kind == EnvironmentMutationKind.PACKAGE_INSTALL:
                if entry.new_state.lower() in ("uninstalled", "removed"):
                    installed_packages.pop(entry.target_name, None)
                else:
                    installed_packages[entry.target_name] = entry.new_state

            elif entry.kind == EnvironmentMutationKind.MCP_TOOL_MOUNT:
                if entry.new_state.lower() in ("unmounted", "disabled", "removed"):
                    active_mcp_servers.discard(entry.target_name)
                else:
                    active_mcp_servers.add(entry.target_name)

            elif entry.kind == EnvironmentMutationKind.ENV_VAR_CHANGE:
                if entry.new_state.lower() in ("unset", ""):
                    effective_env_vars.pop(entry.target_name, None)
                else:
                    effective_env_vars[entry.target_name] = entry.new_state

        summary_lines: list[str] = [
            f"- Installed Packages ({len(installed_packages)}): "
            + (", ".join(f"{k}=={v}" for k, v in sorted(installed_packages.items())) if installed_packages else "none"),
            f"- Active MCP Servers ({len(active_mcp_servers)}): "
            + (", ".join(sorted(active_mcp_servers)) if active_mcp_servers else "none"),
            f"- Effective Env Vars ({len(effective_env_vars)}): "
            + (", ".join(sorted(effective_env_vars.keys())) if effective_env_vars else "none"),
        ]

        return EnvironmentStateDigest(
            installed_packages=installed_packages,
            active_mcp_servers=sorted(active_mcp_servers),
            effective_env_vars=effective_env_vars,
            recent_changes_count=len(entries),
            last_mutation_timestamp=last_timestamp,
            summary_markdown="\n".join(summary_lines),
        )

    def render_anti_amnesia_prompt(
        self, digest: EnvironmentStateDigest | None = None
    ) -> RehydrationInjectionPayload:
        """Generate prompt block to eliminate cross-session amnesia after resets or compactions."""
        current_digest = digest or self.generate_state_digest()

        time_str = "N/A"
        if current_digest.last_mutation_timestamp is not None:
            time_str = datetime.fromtimestamp(
                current_digest.last_mutation_timestamp, tz=UTC
            ).strftime("%Y-%m-%d %H:%M:%S UTC")

        packages_desc = (
            ", ".join(f"{k}=={v}" for k, v in sorted(current_digest.installed_packages.items()))
            if current_digest.installed_packages
            else "none"
        )
        mcp_desc = (
            ", ".join(current_digest.active_mcp_servers)
            if current_digest.active_mcp_servers
            else "none"
        )
        env_desc = (
            ", ".join(sorted(current_digest.effective_env_vars.keys()))
            if current_digest.effective_env_vars
            else "none"
        )

        prompt_block = (
            "<environment_state_digest>\n"
            "[CRITICAL CONTEXT: The sandbox workspace has already evolved with the verified state below. "
            "Do NOT duplicate installation of existing packages or tools.]\n"
            f"- Verified Packages: {packages_desc}\n"
            f"- Active MCP Tools: {mcp_desc}\n"
            f"- Custom Env Vars: {env_desc}\n"
            f"- Last Mutation Timestamp: {time_str}\n"
            "</environment_state_digest>"
        )

        token_estimate = max(1, len(prompt_block) // 4)
        return RehydrationInjectionPayload(
            digest=current_digest,
            prompt_block=prompt_block,
            token_count_estimate=token_estimate,
        )

    def parse_bash_execution_for_mutations(
        self, command: str, stdout: str = "", exit_code: int = 0
    ) -> list[EnvironmentChangelogEntry]:
        """Heuristically inspect bash command and stdout to automatically register mutations."""
        if exit_code != 0:
            return []

        discovered: list[EnvironmentChangelogEntry] = []

        # 1. Detect Python package installations (uv / pip)
        py_match = re.search(r"(?:uv\s+pip\s+install|pip\s+install)\s+([a-zA-Z0-9_\-=>.<]+)", command)
        if py_match:
            pkg_spec = py_match.group(1).strip()
            name_part = pkg_spec.split("==")[0].split(">=")[0].strip()
            version_match = re.search(rf"Successfully installed .*{re.escape(name_part)}-([0-9a-zA-Z.]+)", stdout)
            version_str = version_match.group(1) if version_match else "installed"

            entry = self.record_mutation(
                kind=EnvironmentMutationKind.PACKAGE_INSTALL,
                target_name=name_part,
                new_state=version_str,
                rationale=f"Auto-detected from bash: {command}",
            )
            discovered.append(entry)

        # 2. Detect Node package installations (npm / pnpm / yarn / bun)
        node_match = re.search(r"(?:npm\s+install|npm\s+i|pnpm\s+add|yarn\s+add|bun\s+add)\s+([a-zA-Z0-9_\-@/]+)", command)
        if node_match:
            pkg_name = node_match.group(1).strip()
            entry = self.record_mutation(
                kind=EnvironmentMutationKind.PACKAGE_INSTALL,
                target_name=pkg_name,
                new_state="installed",
                rationale=f"Auto-detected from bash: {command}",
            )
            discovered.append(entry)

        # 3. Detect environment variable exports
        env_match = re.search(r"export\s+([A-Z0-9_]+)=([^\s;&]+)", command)
        if env_match:
            var_name = env_match.group(1).strip()
            var_val = env_match.group(2).strip()
            entry = self.record_mutation(
                kind=EnvironmentMutationKind.ENV_VAR_CHANGE,
                target_name=var_name,
                new_state=var_val,
                rationale=f"Auto-detected env export: {command}",
            )
            discovered.append(entry)

        return discovered

    def export_markdown_timeline(self) -> str:
        """Render human-readable markdown timeline for WebUI or developer audits."""
        with self._lock:
            entries = list(self._entries)

        if not entries:
            return "### Environment Mutation Timeline\n*No modifications recorded.*"

        lines = ["### Environment Mutation Timeline"]
        for e in entries:
            t_str = datetime.fromtimestamp(e.timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
            old_part = f"`{e.old_state}` -> " if e.old_state else ""
            lines.append(
                f"- `{t_str}` [{e.actor.upper()}] ({e.kind.value}) **{e.target_name}**: "
                f"{old_part}`{e.new_state}`"
                + (f" *({e.rationale})*" if e.rationale else "")
            )
        return "\n".join(lines)

    def export_jsonl(self) -> str:
        """Export machine-readable JSONL stream."""
        with self._lock:
            entries = list(self._entries)

        rows: list[str] = []
        for e in entries:
            payload = {
                "entry_id": e.entry_id,
                "timestamp": e.timestamp,
                "actor": e.actor.value,
                "kind": e.kind.value,
                "target_name": e.target_name,
                "old_state": e.old_state,
                "new_state": e.new_state,
                "rationale": e.rationale,
                "is_verified": e.is_verified,
            }
            rows.append(json.dumps(payload, ensure_ascii=False))
        return "\n".join(rows)

    def load_jsonl(self, jsonl_content: str) -> int:
        """Hydrate ledger from JSONL content; returns number of entries loaded."""
        loaded_count = 0
        new_entries: list[EnvironmentChangelogEntry] = []
        for line in jsonl_content.splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            entry = EnvironmentChangelogEntry(
                entry_id=data["entry_id"],
                timestamp=float(data["timestamp"]),
                actor=MutationActor(data.get("actor", MutationActor.AGENT)),
                kind=EnvironmentMutationKind(data["kind"]),
                target_name=data["target_name"],
                old_state=data.get("old_state"),
                new_state=data["new_state"],
                rationale=data.get("rationale", ""),
                is_verified=bool(data.get("is_verified", True)),
            )
            new_entries.append(entry)
            loaded_count += 1

        with self._lock:
            self._entries.extend(new_entries)
        return loaded_count
