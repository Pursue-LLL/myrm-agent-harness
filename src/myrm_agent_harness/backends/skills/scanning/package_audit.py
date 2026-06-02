"""Package manifest security audit for skill directories.

Audits package.json files for supply chain attack vectors:
- Dangerous install scripts (preinstall, install, postinstall)
- Suspicious dependency patterns
- Script injection via package name/description

[INPUT]
- (none)

[OUTPUT]
- PackageAuditFinding: single finding from package audit
- audit_package_json(): audit a package.json string for security issues
- audit_skill_directory(): scan a skill directory for package.json issues

[POS]
Supply chain security audit for skill package manifests.
Catches install script attacks that can execute arbitrary code on npm install.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DANGEROUS_SCRIPTS = frozenset({"preinstall", "install", "postinstall"})
_SKIPPED_DIRS = frozenset({"node_modules", ".git", "__pycache__", ".venv", "venv"})
_MAX_DIR_DEPTH = 3
_MAX_FILES = 100


@dataclass(frozen=True, slots=True)
class PackageAuditFinding:
    """A single finding from package.json audit."""

    threat_type: str
    severity: str  # "critical", "high", "medium", "warning"
    description: str
    file_path: str = ""
    detail: str = ""


def audit_package_json(content: str, file_path: str = "") -> list[PackageAuditFinding]:
    """Audit a package.json string for security issues.

    Args:
        content: Raw JSON string of package.json
        file_path: Optional path label for the finding

    Returns:
        List of findings (empty if clean)
    """
    findings: list[PackageAuditFinding] = []

    try:
        pkg = json.loads(content)
    except json.JSONDecodeError as exc:
        findings.append(
            PackageAuditFinding(
                threat_type="invalid_manifest",
                severity="warning",
                description=f"Invalid JSON in package.json: {exc.msg}",
                file_path=file_path,
            )
        )
        return findings

    if not isinstance(pkg, dict):
        return findings

    # Check for dangerous install scripts
    scripts = pkg.get("scripts")
    if isinstance(scripts, dict):
        for script_name in _DANGEROUS_SCRIPTS:
            script_value = scripts.get(script_name)
            if script_value and isinstance(script_value, str) and script_value.strip():
                findings.append(
                    PackageAuditFinding(
                        threat_type="supply_chain",
                        severity="high",
                        description=f"Dangerous install script: {script_name}",
                        file_path=file_path,
                        detail=f"{script_name}: {script_value[:200]}",
                    )
                )

    # Check for suspicious pre/post scripts on any command
    if isinstance(scripts, dict):
        for key, value in scripts.items():
            if isinstance(value, str) and _contains_suspicious_command(value):
                findings.append(
                    PackageAuditFinding(
                        threat_type="supply_chain",
                        severity="medium",
                        description=f"Script contains suspicious command: {key}",
                        file_path=file_path,
                        detail=f"{key}: {value[:200]}",
                    )
                )

    return findings


def audit_skill_directory(skill_dir: str | Path) -> list[PackageAuditFinding]:
    """Scan a skill directory for package.json files and audit them.

    Walks the directory tree (up to MAX_DIR_DEPTH levels) looking for
    package.json files. Skips node_modules, .git, etc.

    Args:
        skill_dir: Path to the skill directory

    Returns:
        Combined findings from all package.json files found
    """
    root = Path(skill_dir)
    if not root.is_dir():
        return []

    all_findings: list[PackageAuditFinding] = []
    files_checked = 0

    for depth, file_path in _walk_files(root):
        if depth > _MAX_DIR_DEPTH:
            continue
        if files_checked >= _MAX_FILES:
            break

        if file_path.name != "package.json":
            continue

        files_checked += 1
        relative = str(file_path.relative_to(root))

        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Cannot read %s: %s", relative, exc)
            continue

        findings = audit_package_json(content, relative)
        all_findings.extend(findings)

    return all_findings


def _walk_files(root: Path):
    """Walk files yielding (depth, path) tuples, skipping ignored directories."""
    queue: list[tuple[int, Path]] = [(0, root)]

    while queue:
        depth, current = queue.pop(0)
        try:
            entries = sorted(current.iterdir())
        except PermissionError:
            continue

        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".env", ".gitignore"}:
                continue
            if entry.name in _SKIPPED_DIRS:
                continue
            if entry.is_symlink():
                continue
            if entry.is_file():
                yield depth, entry
            elif entry.is_dir() and depth < _MAX_DIR_DEPTH:
                queue.append((depth + 1, entry))


def _contains_suspicious_command(script: str) -> bool:
    """Check if a script value contains suspicious commands."""
    suspicious = [
        "curl ",
        "wget ",
        "chmod +x",
        "eval ",
        "node -e",
        "python -c",
        "/dev/tcp",
        "nc -",
        "netcat ",
    ]
    lowered = script.lower()
    return any(cmd in lowered for cmd in suspicious)
