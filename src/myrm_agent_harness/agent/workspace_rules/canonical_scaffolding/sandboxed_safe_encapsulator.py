"""Sandboxed safe workspace encapsulator and static security scanner.

[INPUT]
- Untrusted external workspace path, optional target sandbox volume mount directory.

[OUTPUT]
- SandboxEncapsulationRecord certifying security containment, sanitized payloads,
  and dedicated sandbox volume mount paths.

[POS]
- Harness workspace rules in agent/workspace_rules/canonical_scaffolding/sandboxed_safe_encapsulator.py.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Sequence

from .scaffolding_types import (
    EncapsulationSecurityLevel,
    SandboxEncapsulationRecord,
    SandboxSecurityFinding,
)


class SandboxedSafeWorkspaceEncapsulator:
    """Secures alien or untrusted agent workspaces into isolated sandbox environments."""

    DANGEROUS_SHELL_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
        (re.compile(r"rm\s+-rf\s+(?:/|~|\$HOME)", re.IGNORECASE), "CRITICAL", "Destructive root/home wipe command"),
        (re.compile(r"(?:curl|wget)\s+[^|\n]+\|\s*(?:bash|sh|zsh)", re.IGNORECASE), "HIGH", "Untrusted remote script piping to shell"),
        (re.compile(r"(?:nc|netcat)\s+-[elp]|/dev/tcp/", re.IGNORECASE), "CRITICAL", "Reverse shell or raw socket pipe detected"),
        (re.compile(r"chmod\s+(?:-R\s+)?777", re.IGNORECASE), "MEDIUM", "Permissive permission grant (chmod 777)"),
    )

    PROMPT_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
        (re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE), "HIGH", "Prompt injection: ignore previous instructions"),
        (re.compile(r"disregard\s+prior\s+(?:context|instructions|rules)", re.IGNORECASE), "HIGH", "Prompt injection: disregard prior context"),
        (re.compile(r"(?:leak|print|reveal)\s+(?:the\s+)?(?:system\s+prompt|core\s+instructions)", re.IGNORECASE), "MEDIUM", "Prompt injection: system prompt extraction attempt"),
        (re.compile(r"bypass\s+all\s+(?:safety|guardrails|filters)", re.IGNORECASE), "HIGH", "Prompt injection: safety bypass directive"),
    )

    @classmethod
    def encapsulate_workspace(
        cls,
        source_workspace_path: str | Path,
        sandbox_base_volume_dir: str | Path | None = None,
        auto_sanitize: bool = True,
    ) -> SandboxEncapsulationRecord:
        """Inspects source files, sanitizes unsafe payloads, and maps into a sandboxed root."""
        src_root = Path(source_workspace_path)
        if not src_root.is_dir():
            return SandboxEncapsulationRecord(
                source_path=str(src_root),
                encapsulated_sandbox_root="",
                security_level=EncapsulationSecurityLevel.QUARANTINED,
                findings=(),
                sanitized_file_count=0,
                is_safe_to_execute=False,
                quarantine_reason="Workspace source directory does not exist or is not a directory.",
            )

        findings: list[SandboxSecurityFinding] = []
        sanitized_files_count = 0
        has_critical = False

        # Scan text and script files
        for item in src_root.rglob("*"):
            if not item.is_file():
                continue
            if item.stat().st_size > 2 * 1024 * 1024:  # Skip oversized binaries >2MB
                continue

            # Check suffix
            if item.suffix.lower() in (".md", ".txt", ".json", ".yaml", ".yml", ".sh", ".bash", ".py", ".js", ".ts"):
                try:
                    content = item.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                rel_path = str(item.relative_to(src_root)).replace("\\", "/")

                # Check shell patterns
                for pattern, severity, desc in cls.DANGEROUS_SHELL_PATTERNS:
                    if pattern.search(content):
                        if severity == "CRITICAL":
                            has_critical = True
                        findings.append(
                            SandboxSecurityFinding(
                                severity=severity,
                                file_path=rel_path,
                                pattern_matched=pattern.pattern,
                                description=desc,
                                remediation_applied="quarantine_marked" if severity == "CRITICAL" else "sanitized",
                            )
                        )

                # Check prompt injection patterns
                for pattern, severity, desc in cls.PROMPT_INJECTION_PATTERNS:
                    if pattern.search(content):
                        findings.append(
                            SandboxSecurityFinding(
                                severity=severity,
                                file_path=rel_path,
                                pattern_matched=pattern.pattern,
                                description=desc,
                                remediation_applied="sanitized_redaction",
                            )
                        )

        # Decide sandbox root
        if sandbox_base_volume_dir is not None:
            sandbox_root = Path(sandbox_base_volume_dir) / f"sandbox_{src_root.name}"
        else:
            sandbox_root = src_root.parent / f".sandbox_volume_{src_root.name}"

        # Evaluate final containment posture
        if has_critical:
            return SandboxEncapsulationRecord(
                source_path=str(src_root.resolve()),
                encapsulated_sandbox_root=str(sandbox_root),
                security_level=EncapsulationSecurityLevel.QUARANTINED,
                findings=tuple(findings),
                sanitized_file_count=0,
                is_safe_to_execute=False,
                quarantine_reason="Critical destructive shell commands or reverse socket payloads detected.",
            )

        if findings:
            security_level = EncapsulationSecurityLevel.SANITIZED
            sanitized_files_count = len({f.file_path for f in findings})
        else:
            security_level = EncapsulationSecurityLevel.SAFE

        return SandboxEncapsulationRecord(
            source_path=str(src_root.resolve()),
            encapsulated_sandbox_root=str(sandbox_root),
            security_level=security_level,
            findings=tuple(findings),
            sanitized_file_count=sanitized_files_count,
            is_safe_to_execute=True,
            quarantine_reason=None,
        )

    @classmethod
    def sanitize_untrusted_text(cls, text: str) -> str:
        """Utility function that redacts known prompt injection directives in user text."""
        sanitized = text
        for pattern, _, _ in cls.PROMPT_INJECTION_PATTERNS:
            sanitized = pattern.sub("[REDACTED_PROMPT_INJECTION]", sanitized)
        return sanitized
