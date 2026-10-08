"""Workspace rule file discovery and loading.

Scans the workspace directory for project-level rule files and loads
their content with security scanning and size truncation.

Supported file types:
- Root-level: AGENTS.md, CLAUDE.md, SOUL.md, MEMORY.md, .cursorrules, .clinerules, .myrm.md, .hermes.md, HERMES.md, .windsurfrules
- Directory-based: .myrm/rules/*.md, .cursor/rules/*.mdc, .claude/CLAUDE.md, .github/copilot-instructions.md

All discovered rule files are loaded and concatenated — multiple
rule files can coexist (e.g. .myrm/rules/coding.md + AGENTS.md +
.cursor/rules/style.mdc).

Discovery traverses upward from workspace_root toward the git root
to find rule files in parent directories (max 5 levels).

[INPUT]
- agent.security.detection.prompt_guard::scan_input (POS: Input-side injection detector)
- agent.security.detection.content_boundary::sanitize, detect_suspicious, strip_invisible_unicode (POS: Boundary sanitization and security marker detection)
- agent.workspace_rules.adr_scanner::scan_adr_rules (POS: Living architecture decision record scanner and MADR status filter)

[OUTPUT]
- scan_workspace_rules(): Discover and load all rule files, returns list[RuleFile]
- RuleFile: Dataclass holding path, content, source type, blocked flag

[POS]
Workspace rule file scanner. Discovers project-level context files
(AGENTS.md, CLAUDE.md, SOUL.md, MEMORY.md, .cursorrules, .clinerules,
.myrm.md, .hermes.md, HERMES.md, .windsurfrules, .myrm/rules/*.md,
.cursor/rules/*.mdc, .claude/CLAUDE.md, .github/copilot-instructions.md),
performs security scanning, YAML frontmatter stripping, and returns
loaded content for middleware injection. Blocked files (injection
detected) return a placeholder RuleFile with blocked=True instead of
being silently skipped.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_RULE_FILE_CHARS = 8000
MAX_TOTAL_CHARS = 20000
MAX_UPWARD_LEVELS = 5
_CODE_FENCE_PATTERN = re.compile(r"^\s*```", re.MULTILINE)

_RULE_FILENAMES: tuple[str, ...] = (
    ".myrm.md",
    "myrm.md",
    ".hermes.md",
    "HERMES.md",
    "SOUL.md",
    "soul.md",
    "MEMORY.md",
    "memory.md",
    "AGENTS.md",
    "agents.md",
    "CLAUDE.md",
    "claude.md",
    "HEARTBEAT.md",
    "heartbeat.md",
    "OPPORTUNITY.md",
    "opportunity.md",
    ".goosehints",
    "goosehints",
    ".traerules",
    ".cursorrules",
    ".clinerules",
    ".windsurfrules",
)

_MYRM_RULES_DIR = ".myrm/rules"
_CURSOR_RULES_DIR = ".cursor/rules"
_TRAE_RULES_DIR = ".trae/rules"
_CLAUDE_SUBDIR_FILE = ".claude/CLAUDE.md"
_COPILOT_INSTRUCTIONS_FILE = ".github/copilot-instructions.md"
_KNOWN_ISSUES_FILENAMES: tuple[str, ...] = ("KNOWN_ISSUES.md", "known_issues.md")


@dataclass(frozen=True, slots=True)
class RuleFile:
    """A discovered and loaded workspace rule file."""

    path: str
    content: str
    source: str
    truncated: bool = False
    blocked: bool = False


def _find_git_root(start: Path) -> Path | None:
    """Walk upward to find the nearest .git directory."""
    current = start.resolve()
    for _ in range(MAX_UPWARD_LEVELS):
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _check_content_safety(content: str, filepath: str) -> tuple[bool, list[str]]:
    """Run security scans on rule file content.

    Returns (safe, blocked_patterns) where blocked_patterns is non-empty
    only when the content is blocked (safe=False).
    """
    from myrm_agent_harness.agent.security.detection.content_boundary import (
        detect_suspicious,
    )
    from myrm_agent_harness.agent.security.detection.prompt_guard import (
        scan_input,
    )

    guard_result = scan_input(content)
    if not guard_result.safe and guard_result.max_score >= 0.8:
        logger.warning(
            "Workspace rule file blocked (injection detected): %s patterns=%s score=%.2f",
            filepath,
            ",".join(guard_result.patterns),
            guard_result.max_score,
        )
        return False, guard_result.patterns

    suspicious = detect_suspicious(content)
    if suspicious:
        logger.warning(
            "Workspace rule file suspicious patterns: %s patterns=%s",
            filepath,
            ",".join(suspicious),
        )

    return True, []


def _strip_yaml_frontmatter(text: str) -> str:
    """Remove optional YAML frontmatter (``---`` delimited) from rule content.

    Frontmatter is stripped to avoid injecting non-human-readable
    structured metadata (e.g. IDE-specific globs, model overrides) into
    the system prompt. Only the prose body is injected.
    """
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body = text[end + 4 :].lstrip("\n")
            return body if body else text
    return text


def _truncate_with_markdown_repair(
    content: str,
    filename: str,
    max_chars: int = MAX_RULE_FILE_CHARS,
) -> str:
    """Truncate content with newline alignment and Markdown fence closure repair.

    Protects System Prompt context from syntax tearing:
    1. Aligns head cut to the nearest preceding newline within a search window.
    2. Aligns tail cut to the nearest following newline within a search window.
    3. Closes any open Markdown code fences at the end of head segment.
    4. Re-opens any severed Markdown code fences at the start of tail segment.
    """
    head_target = int(max_chars * 0.7)
    tail_target = int(max_chars * 0.2)

    # 1. Align head to nearest preceding newline (look back up to 500 chars)
    head_cut = content.rfind("\n", max(0, head_target - 500), head_target)
    head = content[:head_cut] if head_cut != -1 else content[:head_target]

    # 2. Align tail to nearest following newline (look ahead up to 500 chars)
    tail_start = len(content) - tail_target
    tail_cut = content.find("\n", tail_start, min(len(content), tail_start + 500))
    tail = content[tail_cut + 1 :] if tail_cut != -1 else content[tail_start:]

    # 3. Detect unclosed code fences in head (odd count means open fence)
    if len(_CODE_FENCE_PATTERN.findall(head)) % 2 != 0:
        head = f"{head}\n```"

    # 4. Detect orphaned code fences in tail (odd count means severed start)
    if len(_CODE_FENCE_PATTERN.findall(tail)) % 2 != 0:
        tail = f"```\n{tail}"

    return (
        f"{head}\n\n[...truncated {filename}: "
        f"kept {len(head)}+{len(tail)} of {len(content)} chars]\n\n{tail}"
    )


def _load_rule_file(filepath: Path, source: str) -> RuleFile | None:
    """Load, sanitize, and validate a single rule file.

    Returns None if the file is missing, empty, or unreadable.
    Returns RuleFile(blocked=True) if prompt injection patterns are detected.
    Truncates content exceeding MAX_RULE_FILE_CHARS with Markdown fence repair.
    """
    try:
        raw = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Failed to read workspace rule file %s: %s", filepath, exc)
        return None

    if not raw.strip():
        return None

    from myrm_agent_harness.agent.security.detection.content_boundary import (
        sanitize,
        strip_invisible_unicode,
    )

    content = strip_invisible_unicode(raw)
    content = _strip_yaml_frontmatter(content)
    content = sanitize(content)

    safe, blocked_patterns = _check_content_safety(content, str(filepath))
    if not safe:
        filename = os.path.basename(str(filepath))
        patterns_str = ", ".join(blocked_patterns)
        placeholder = (
            f"[BLOCKED: {filename} — potential prompt injection detected "
            f"({patterns_str}). Content not loaded for safety.]"
        )
        return RuleFile(
            path=str(filepath),
            content=placeholder,
            source=source,
            blocked=True,
        )

    was_truncated = False
    if len(content) > MAX_RULE_FILE_CHARS:
        content = _truncate_with_markdown_repair(
            content=content,
            filename=os.path.basename(str(filepath)),
            max_chars=MAX_RULE_FILE_CHARS,
        )
        was_truncated = True
        logger.info(
            "Workspace rule file truncated (head/tail with fence repair) to %d chars: %s",
            MAX_RULE_FILE_CHARS,
            filepath,
        )

    return RuleFile(path=str(filepath), content=content, source=source, truncated=was_truncated)


def _inode_key(filepath: Path) -> tuple[int, int]:
    """Return (device, inode) pair for dedup on case-insensitive filesystems."""
    stat = filepath.stat()
    return (stat.st_dev, stat.st_ino)


def _scan_rules_subdir(
    directory: Path,
    subdir: str,
    glob_pattern: str,
    seen_inodes: set[tuple[int, int]],
) -> list[RuleFile]:
    """Scan a subdirectory for rule files matching the glob pattern."""
    rules_dir = directory / subdir
    if not rules_dir.is_dir():
        return []

    results: list[RuleFile] = []
    try:
        for rule_file in sorted(rules_dir.glob(glob_pattern)):
            if rule_file.is_file():
                key = _inode_key(rule_file)
                if key in seen_inodes:
                    continue
                seen_inodes.add(key)
                rule = _load_rule_file(rule_file, source=subdir)
                if rule:
                    results.append(rule)
    except OSError as exc:
        logger.warning("Failed to scan %s: %s", subdir, exc)
    return results


def _scan_directory(directory: Path) -> list[RuleFile]:
    """Scan a single directory for rule files.

    Uses First-Match-Wins for global rule files to prevent conflicts,
    but always loads specific rule directories (.myrm/rules, .cursor/rules).
    """
    results: list[RuleFile] = []
    seen_inodes: set[tuple[int, int]] = set()

    # 1. Load specific rule directories (always loaded)
    results.extend(_scan_rules_subdir(directory, _MYRM_RULES_DIR, "*.md", seen_inodes))
    results.extend(_scan_rules_subdir(directory, _CURSOR_RULES_DIR, "*.mdc", seen_inodes))
    results.extend(_scan_rules_subdir(directory, _TRAE_RULES_DIR, "*.md", seen_inodes))

    # 2. Load living architectural decision records (MADR / docs/decisions/*.md)
    from myrm_agent_harness.agent.workspace_rules.adr_scanner import scan_adr_rules

    results.extend(scan_adr_rules(directory, seen_inodes))

    # 3. Load living known issues and environment pitfalls (KNOWN_ISSUES.md)
    for filename in _KNOWN_ISSUES_FILENAMES:
        filepath = directory / filename
        if filepath.is_file():
            key = _inode_key(filepath)
            if key not in seen_inodes:
                seen_inodes.add(key)
                rule = _load_rule_file(filepath, source=filename)
                if rule:
                    results.append(rule)
                    break

    # 4. First-Match-Wins for global rule files
    for filename in _RULE_FILENAMES:
        filepath = directory / filename
        if filepath.is_file():
            key = _inode_key(filepath)
            if key not in seen_inodes:
                seen_inodes.add(key)
                rule = _load_rule_file(filepath, source=filename)
                if rule:
                    results.append(rule)
                    return results  # Stop after finding the highest priority global file

    # 3. Check fallback subdirectories if no global file was found
    for subdir_file in (_CLAUDE_SUBDIR_FILE, _COPILOT_INSTRUCTIONS_FILE):
        filepath = directory / subdir_file
        if filepath.is_file():
            key = _inode_key(filepath)
            if key not in seen_inodes:
                seen_inodes.add(key)
                rule = _load_rule_file(filepath, source=subdir_file)
                if rule:
                    results.append(rule)
                    return results  # Stop after finding the highest priority fallback

    return results


def scan_workspace_rules(workspace_root: str) -> list[RuleFile]:
    """Discover and load workspace rule files.

    Scans from workspace_root upward to git root (max 5 levels).
    Within each directory, uses First-Match-Wins priority loading to prevent
    conflicts (e.g., AGENTS.md > .cursorrules).
    Content is security-scanned and truncated to budget.

    Args:
        workspace_root: The agent's workspace root directory.

    Returns:
        List of loaded rule files, ordered by directory depth
        (workspace_root first, then parent directories).
    """
    if not workspace_root:
        return []

    root = Path(workspace_root)
    if not root.is_dir():
        return []

    results: list[RuleFile] = []
    scanned: set[Path] = set()
    total_chars = 0

    git_root = _find_git_root(root)
    ceiling = git_root if git_root else root

    current = root.resolve()
    for _ in range(MAX_UPWARD_LEVELS):
        if current in scanned:
            break
        scanned.add(current)

        for rule in _scan_directory(current):
            if total_chars + len(rule.content) > MAX_TOTAL_CHARS:
                logger.info("Workspace rules total budget exceeded, skipping: %s", rule.path)
                continue
            results.append(rule)
            total_chars += len(rule.content)

        if current == ceiling or current.parent == current:
            break
        current = current.parent

    if results:
        logger.info(
            "Loaded %d workspace rule file(s): %s",
            len(results),
            ", ".join(os.path.basename(r.path) for r in results),
        )

    return results
