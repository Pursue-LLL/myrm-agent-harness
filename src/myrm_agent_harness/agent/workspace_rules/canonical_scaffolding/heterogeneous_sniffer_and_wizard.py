"""Heterogeneous workspace adaptive sniffer and zero-friction handover wizard.

[INPUT]
- Root path to an external or local agent workspace (Path or str).

[OUTPUT]
- EcosystemSniffResult fingerprinting origin architectures.
- CanonicalScaffoldingManifest smoothly mapping heterogeneous layouts to canonical Myrm profiles.

[POS]
- Harness workspace rules in agent/workspace_rules/canonical_scaffolding/heterogeneous_sniffer_and_wizard.py.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Sequence

from .scaffolding_types import (
    CanonicalScaffoldingManifest,
    EcosystemSniffResult,
    ScaffoldingFileEntry,
    WorkspaceEcosystemSource,
)


class HeterogeneousWorkspaceSnifferAndWizard:
    """Fingerprints alien agent workspaces and converts them seamlessly into canonical structures."""

    PERSONA_TITLE_REGEX = re.compile(r"^#+\s+(?:Name|Persona|Role|Identity)?[:\-]?\s*(.+)$", re.MULTILINE | re.IGNORECASE)

    @classmethod
    def sniff_ecosystem(cls, root_path: str | Path) -> EcosystemSniffResult:
        """Deeply inspects file markers, directory structure, and content patterns."""
        root = Path(root_path)
        if not root.is_dir():
            return EcosystemSniffResult(
                matched_ecosystem=WorkspaceEcosystemSource.GENERIC_PROJECT,
                confidence=0.0,
                signature_evidence=("Path is not a valid directory.",),
            )

        evidence: list[str] = []
        matched_ecosystem = WorkspaceEcosystemSource.GENERIC_PROJECT
        confidence = 0.5
        detected_persona = "Standard Assistant"

        # Check Meta Muse signature
        if (root / ".muse").is_dir() or (root / "muse.config.json").is_file():
            matched_ecosystem = WorkspaceEcosystemSource.META_MUSE
            confidence = 0.95
            evidence.append("Found Meta Muse marker (.muse/ or muse.config.json).")
        # Check Hermes signature
        elif (root / "hermes.json").is_file() or (root / ".hermes").is_dir():
            matched_ecosystem = WorkspaceEcosystemSource.HERMES
            confidence = 0.95
            evidence.append("Found Hermes Agent configuration marker (hermes.json or .hermes/).")
        # Check Cursor / Windsurf IDE rules signature
        elif (root / ".cursorrules").is_file() or (root / ".cursor" / "rules").is_dir() or (root / ".windsurfrules").is_file():
            matched_ecosystem = WorkspaceEcosystemSource.CURSOR_WINDSURF
            confidence = 0.90
            evidence.append("Found IDE workspace rules (.cursorrules, .cursor/rules, or .windsurfrules).")
        # Check OpenClaw signature (soul.md + skills/ + agents/)
        elif (root / "soul.md").is_file() and ((root / "skills").is_dir() or (root / "agents").is_dir()):
            matched_ecosystem = WorkspaceEcosystemSource.OPEN_CLAW
            confidence = 0.92
            evidence.append("Found OpenClaw canonical scaffolding signature (soul.md + skills/agents).")
        # Check Canonical Myrm
        elif (root / "SOUL.md").is_file() and ((root / "MEMORY.md").is_file() or (root / "HEARTBEAT.md").is_file()):
            matched_ecosystem = WorkspaceEcosystemSource.CANONICAL_MYRM
            confidence = 0.98
            evidence.append("Found Canonical Myrm signature (SOUL.md + MEMORY.md/HEARTBEAT.md).")
        else:
            evidence.append("No specialized agent signatures detected; classified as Generic Project.")

        # Extract persona title if soul file exists
        soul_candidate = cls._find_candidate_file(root, ("SOUL.md", "soul.md", ".cursorrules", ".windsurfrules"))
        if soul_candidate and soul_candidate.is_file():
            content = soul_candidate.read_text(encoding="utf-8", errors="replace")
            match = cls.PERSONA_TITLE_REGEX.search(content[:1024])
            if match:
                detected_persona = match.group(1).strip()
            elif len(content.strip()) > 0:
                first_line = content.strip().splitlines()[0]
                cleaned = re.sub(r"^[#\s\-*]+", "", first_line).strip()
                if cleaned:
                    detected_persona = cleaned

        rule_count = cls._count_files_in_dir(root / "rules")
        if (root / ".cursor" / "rules").is_dir():
            rule_count += cls._count_files_in_dir(root / ".cursor" / "rules")

        skill_count = cls._count_files_in_dir(root / "skills")
        has_memory = (root / "MEMORY.md").is_file() or (root / "memory.md").is_file() or (root / "memory").is_dir()

        return EcosystemSniffResult(
            matched_ecosystem=matched_ecosystem,
            confidence=confidence,
            signature_evidence=tuple(evidence),
            detected_persona_title=detected_persona,
            extracted_rule_count=rule_count,
            extracted_skill_count=skill_count,
            has_custom_memory=has_memory,
        )

    @classmethod
    def adapt_to_canonical_manifest(cls, root_path: str | Path) -> CanonicalScaffoldingManifest:
        """Inspects all heterogeneous artifacts and generates a normalized canonical manifest."""
        root = Path(root_path)
        sniff_result = cls.sniff_ecosystem(root)

        soul_file = cls._find_candidate_file(root, ("SOUL.md", "soul.md", ".cursorrules", ".windsurfrules"))
        user_file = cls._find_candidate_file(root, ("USER.md", "user.md", "identity.md"))
        memory_file = cls._find_candidate_file(root, ("MEMORY.md", "memory.md"))
        heartbeat_file = cls._find_candidate_file(root, ("HEARTBEAT.md", "heartbeat.md"))

        agents_dir = cls._find_candidate_dir(root, ("agents",))
        rules_dir = cls._find_candidate_dir(root, ("rules", ".cursor/rules"))
        skills_dir = cls._find_candidate_dir(root, ("skills",))
        context_dir = cls._find_candidate_dir(root, ("context",))

        file_entries: list[ScaffoldingFileEntry] = []
        for file_path in sorted(root.rglob("*.md")):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(root)).replace("\\", "/")
            if any(part.startswith(".") and part not in (".cursor", ".hermes") for part in file_path.parts):
                continue
            role = cls._classify_file_role(rel)
            content = file_path.read_text(encoding="utf-8", errors="replace")
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            file_entries.append(
                ScaffoldingFileEntry(
                    relative_path=rel,
                    role=role,
                    content_char_count=len(content),
                    is_required=(role in ("soul", "memory")),
                    digest_sha256=digest,
                )
            )

        metadata: dict[str, str] = {
            "persona_title": sniff_result.detected_persona_title,
            "sniff_confidence": str(sniff_result.confidence),
        }

        return CanonicalScaffoldingManifest(
            workspace_root=str(root.resolve()),
            ecosystem_origin=sniff_result.matched_ecosystem,
            soul_file=str(soul_file.relative_to(root)).replace("\\", "/") if soul_file else None,
            user_file=str(user_file.relative_to(root)).replace("\\", "/") if user_file else None,
            memory_file=str(memory_file.relative_to(root)).replace("\\", "/") if memory_file else None,
            heartbeat_file=str(heartbeat_file.relative_to(root)).replace("\\", "/") if heartbeat_file else None,
            agents_dir=str(agents_dir.relative_to(root)).replace("\\", "/") if agents_dir else None,
            rules_dir=str(rules_dir.relative_to(root)).replace("\\", "/") if rules_dir else None,
            skills_dir=str(skills_dir.relative_to(root)).replace("\\", "/") if skills_dir else None,
            context_dir=str(context_dir.relative_to(root)).replace("\\", "/") if context_dir else None,
            all_files=tuple(file_entries),
            metadata=metadata,
        )

    @staticmethod
    def _find_candidate_file(root: Path, candidates: tuple[str, ...]) -> Path | None:
        if not root.is_dir():
            return None
        existing_files = {f.name: f for f in root.iterdir() if f.is_file()}
        # 1. Exact case match
        for candidate in candidates:
            if candidate in existing_files:
                return existing_files[candidate]
        # 2. Case-insensitive match, return actual file on disk
        existing_lower = {f.name.lower(): f for f in root.iterdir() if f.is_file()}
        for candidate in candidates:
            if candidate.lower() in existing_lower:
                return existing_lower[candidate.lower()]
        return None

    @staticmethod
    def _find_candidate_dir(root: Path, candidates: tuple[str, ...]) -> Path | None:
        for candidate in candidates:
            target = root / candidate
            if target.is_dir():
                return target
        return None

    @staticmethod
    def _count_files_in_dir(directory: Path) -> int:
        if not directory.is_dir():
            return 0
        return sum(1 for item in directory.rglob("*") if item.is_file())

    @staticmethod
    def _classify_file_role(rel_path: str) -> str:
        lower = rel_path.lower()
        if "soul" in lower or lower in (".cursorrules", ".windsurfrules"):
            return "soul"
        if "user" in lower:
            return "user"
        if "memory" in lower:
            return "memory"
        if "heartbeat" in lower:
            return "heartbeat"
        if "rules/" in lower or "rules\\" in lower:
            return "rule"
        if "skills/" in lower or "skills\\" in lower:
            return "skill"
        if "agents/" in lower or "agents\\" in lower:
            return "agent"
        return "doc"
