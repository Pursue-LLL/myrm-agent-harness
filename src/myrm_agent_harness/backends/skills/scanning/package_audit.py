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
- audit_package_entry_artifacts(): audit entry files and build artifacts for existence and integrity

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


def audit_package_manifest_dict(pkg: dict[str, object], file_path: str = "") -> list[PackageAuditFinding]:
    """Audit a parsed package.json dictionary for supply chain security issues."""
    findings: list[PackageAuditFinding] = []
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


def check_lifecycle_scripts(files: dict[str, bytes]) -> list[PackageAuditFinding]:
    """Perform pre-extraction and in-memory lifecycle script gate check across files dictionary."""
    findings: list[PackageAuditFinding] = []
    for filename, content in files.items():
        if Path(filename).name.lower() == "package.json":
            try:
                text = content.decode("utf-8", errors="replace")
                findings.extend(audit_package_json(text, filename))
            except Exception as exc:
                logger.debug("Failed to inspect %s for lifecycle scripts: %s", filename, exc)
    return findings


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

        try:
            pkg_dict = json.loads(content)
            if isinstance(pkg_dict, dict):
                artifact_findings = audit_package_entry_artifacts(pkg_dict, file_path.parent, relative)
                all_findings.extend(artifact_findings)
        except Exception as exc:
            logger.debug("Failed parsing %s for artifact checks: %s", relative, exc)

    return all_findings


def audit_package_entry_artifacts(
    pkg: dict[str, object],
    base_dir: Path,
    manifest_rel_path: str = "package.json",
) -> list[PackageAuditFinding]:
    """Audit declared entry points and executable outputs for physical existence and integrity."""
    findings: list[PackageAuditFinding] = []

    # 1. Audit "main" entry
    main_val = pkg.get("main")
    if isinstance(main_val, str) and main_val.strip():
        findings.extend(_verify_entry_artifact(main_val.strip(), base_dir, manifest_rel_path, "main"))

    # 2. Audit "bin" entries
    bin_val = pkg.get("bin")
    if isinstance(bin_val, str) and bin_val.strip():
        findings.extend(_verify_entry_artifact(bin_val.strip(), base_dir, manifest_rel_path, "bin"))
    elif isinstance(bin_val, dict):
        for cmd_name, cmd_path in bin_val.items():
            if isinstance(cmd_path, str) and cmd_path.strip():
                findings.extend(
                    _verify_entry_artifact(cmd_path.strip(), base_dir, manifest_rel_path, f"bin[{cmd_name}]")
                )

    # 3. Audit "exports" entries (supporting conditional exports and nested maps)
    exports_val = pkg.get("exports")
    if exports_val is not None:
        for target in _collect_export_targets(exports_val):
            findings.extend(_verify_entry_artifact(target, base_dir, manifest_rel_path, "exports"))

    return findings


def _collect_export_targets(val: object) -> list[str]:
    """Recursively collect relative file paths from nested conditional exports."""
    targets: list[str] = []
    if isinstance(val, str) and val.strip():
        targets.append(val.strip())
    elif isinstance(val, dict):
        for sub_val in val.values():
            targets.extend(_collect_export_targets(sub_val))
    elif isinstance(val, list):
        for sub_val in val:
            targets.extend(_collect_export_targets(sub_val))
    return targets


def _resolve_artifact_file(base_dir: Path, clean_entry: str) -> Path | None:
    """Resolve physical file respecting Node.js extension and directory index conventions."""
    direct = base_dir / clean_entry
    if direct.is_file():
        return direct

    extensions = (".js", ".cjs", ".mjs", ".json")
    for ext in extensions:
        candidate = base_dir / f"{clean_entry}{ext}"
        if candidate.is_file():
            return candidate

    for ext in extensions:
        candidate = base_dir / clean_entry / f"index{ext}"
        if candidate.is_file():
            return candidate

    return None


def _verify_entry_artifact(
    entry_rel: str,
    base_dir: Path,
    manifest_rel_path: str,
    field_label: str,
) -> list[PackageAuditFinding]:
    """Verify a single declared artifact path exists, is inside base_dir, and is non-empty."""
    findings: list[PackageAuditFinding] = []
    clean_entry = entry_rel.strip()
    if clean_entry.startswith("./") or clean_entry.startswith(".\\"):
        clean_entry = clean_entry[2:]

    parts = clean_entry.replace("\\", "/").split("/")
    if ".." in parts or clean_entry.startswith(("/", "\\")):
        findings.append(
            PackageAuditFinding(
                threat_type="integrity",
                severity="high",
                description=f"Declared {field_label} uses unsafe path traversal: {entry_rel}",
                file_path=manifest_rel_path,
                detail=f"Path traversal blocked: {entry_rel}",
            )
        )
        return findings

    resolved_file = _resolve_artifact_file(base_dir, clean_entry)
    if resolved_file is None:
        ts_hint = ""
        src_dir = base_dir / "src"
        if src_dir.is_dir() and any(src_dir.glob("*.ts")):
            ts_hint = " Detected TypeScript sources in 'src/' but missing compiled outputs. Run 'npm run build' before packaging."

        findings.append(
            PackageAuditFinding(
                threat_type="missing_artifact",
                severity="high",
                description=f"Declared {field_label} entry file not found: {entry_rel}",
                file_path=manifest_rel_path,
                detail=f"Missing file: {clean_entry}.{ts_hint}",
            )
        )
    elif resolved_file.stat().st_size == 0:
        findings.append(
            PackageAuditFinding(
                threat_type="empty_artifact",
                severity="high",
                description=f"Declared {field_label} entry file is empty (0 bytes): {entry_rel}",
                file_path=manifest_rel_path,
                detail=f"Empty file: {clean_entry}",
            )
        )

    return findings


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
