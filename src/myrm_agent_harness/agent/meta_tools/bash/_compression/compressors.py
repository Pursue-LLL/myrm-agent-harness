"""Concrete command-specific output compressors.

Each class implements the Compressor protocol from output_compressor.py,
targeting a specific family of CLI commands (git, test runners, package
managers, build tools, etc.).

[INPUT]
- (none — pure regex-based text transformation)

[OUTPUT]
- GitStatusCompressor, GitDiffCompressor, GitLogCompressor, GitOperationCompressor
- LsCompressor, TestCompressor, PackageInstallCompressor
- DockerBuildCompressor, BuildToolCompressor, CompilerErrorCompressor, LogCompressor

[POS]
Concrete command-specific output compressors for bash tool results.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Git Status Compressor
# ---------------------------------------------------------------------------

_GIT_STATUS_HINT_RE = re.compile(r'^\s*(\(use "git .*\)|（使用 "git .*）|.*（使用 "git .+）)$', re.MULTILINE)
_GIT_STATUS_SECTION_RE = re.compile(
    r"^(Changes to be committed|Changes not staged for commit|Untracked files"
    r"|尚未暂存以备提交的变更|要提交的变更|未跟踪的文件):?$",
    re.MULTILINE,
)
_GIT_STATUS_SECTION_MAP: dict[str, str] = {
    "Changes to be committed:": "staged:",
    "Changes not staged for commit:": "unstaged:",
    "Untracked files:": "untracked:",
    "要提交的变更：": "staged:",
    "尚未暂存以备提交的变更：": "unstaged:",
    "未跟踪的文件：": "untracked:",
}
_GIT_STATUS_CLEAN_MARKERS = (
    "nothing to commit, working tree clean",
    "nothing to commit",
    "无文件要提交，干净的工作区",
)
_GIT_STATUS_PRESENCE = (
    "Changes",
    "Untracked",
    "nothing to commit",
    "尚未暂存",
    "要提交的变更",
    "未跟踪",
    "无文件要提交",
)


class GitStatusCompressor:
    """Compress git status: remove help hints, keep branch + file list."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        if not any(marker in stdout for marker in _GIT_STATUS_PRESENCE):
            return None

        lines = stdout.splitlines()
        result: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if _GIT_STATUS_HINT_RE.match(line):
                continue
            if stripped.startswith(("On branch ", "位于分支 ")):
                branch_name = stripped.replace("On branch ", "").replace("位于分支 ", "")
                result.append(f"branch: {branch_name}")
                continue
            if "Your branch is" in stripped or "您的分支" in stripped:
                info = stripped.replace("Your branch is ", "").replace("您的分支", "").rstrip("。.").strip()
                if result:
                    result[0] += f" ({info})"
                continue
            matched_section = False
            for section_key, section_label in _GIT_STATUS_SECTION_MAP.items():
                if stripped == section_key or stripped.rstrip(":：") == section_key.rstrip(":："):
                    result.append(section_label)
                    matched_section = True
                    break
            if matched_section:
                continue
            if _GIT_STATUS_SECTION_RE.match(stripped):
                result.append(stripped)
                continue
            if any(stripped == m or stripped.startswith(m) for m in _GIT_STATUS_CLEAN_MARKERS):
                result.append("clean")
                continue
            if stripped.startswith(
                (
                    "new file:",
                    "modified:",
                    "deleted:",
                    "renamed:",
                    "typechange:",
                    "新文件：",
                    "修改：",
                    "删除：",
                    "重命名：",
                )
            ) or (stripped and not stripped.startswith("#")):
                result.append(f"  {stripped}")

        compressed = "\n".join(result)
        return compressed if len(compressed) < len(stdout) else None


# ---------------------------------------------------------------------------
# Git Diff Compressor
# ---------------------------------------------------------------------------

_GIT_DIFF_META_RE = re.compile(
    r"^(diff --git |index [0-9a-f]+\.\.[0-9a-f]+|--- [ab]/|--- /dev/null"
    r"|\+\+\+ [ab]/|\+\+\+ /dev/null|similarity index|rename from|rename to"
    r"|new file mode|deleted file mode)"
)


class GitDiffCompressor:
    """Compress git diff: remove meta lines, keep hunks, truncate long hunks."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        if "diff --git" not in stdout and "@@" not in stdout:
            return None

        lines = stdout.splitlines()
        result: list[str] = []

        max_hunk_lines = 100
        hunk_lines_shown = 0
        hunk_lines_hidden = 0
        in_hunk = False
        current_file = "unknown file"

        def _flush_hidden() -> None:
            nonlocal hunk_lines_hidden
            if hunk_lines_hidden > 0:
                result.append(f"[System Note: ... ({hunk_lines_hidden} lines hidden in {current_file}) ...]")
                hunk_lines_hidden = 0

        for line in lines:
            if line.startswith("diff --git"):
                _flush_hidden()
                in_hunk = False
                parts = line.split(" b/")
                current_file = parts[1] if len(parts) > 1 else line.split(" ")[-1]
                result.append(line)
            elif line.startswith("@@"):
                _flush_hidden()
                in_hunk = True
                hunk_lines_shown = 0
                result.append(line)
            elif in_hunk:
                if hunk_lines_shown < max_hunk_lines:
                    result.append(line)
                    hunk_lines_shown += 1
                else:
                    hunk_lines_hidden += 1
            elif not _GIT_DIFF_META_RE.match(line):
                result.append(line)

        _flush_hidden()

        compressed = "\n".join(result)
        return compressed if len(compressed) < len(stdout) * 0.9 else None


# ---------------------------------------------------------------------------
# Git Log Compressor
# ---------------------------------------------------------------------------

_GIT_LOG_COMMIT_RE = re.compile(r"^commit ([0-9a-f]{7,40})")
_GIT_LOG_FIELD_RE = re.compile(r"^(Author|Date|Merge):\s+")


class GitLogCompressor:
    """Compress git log: extract short-hash + first message line."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        if "commit " not in stdout:
            return None

        lines = stdout.splitlines()
        result: list[str] = []
        current_hash = ""
        collecting_message = False

        for line in lines:
            commit_match = _GIT_LOG_COMMIT_RE.match(line)
            if commit_match:
                current_hash = commit_match.group(1)[:7]
                collecting_message = False
                continue
            if _GIT_LOG_FIELD_RE.match(line):
                continue
            stripped = line.strip()
            if not stripped:
                if current_hash and not collecting_message:
                    collecting_message = True
                continue
            if collecting_message and current_hash:
                result.append(f"{current_hash} {stripped}")
                current_hash = ""
                collecting_message = False

        if not result:
            return None
        compressed = "\n".join(result)
        return compressed if len(compressed) < len(stdout) * 0.8 else None


# ---------------------------------------------------------------------------
# Git Operation Compressor (add/commit/push/pull/fetch/merge)
# ---------------------------------------------------------------------------

_GIT_COMMIT_SUCCESS_RE = re.compile(r"^\[(.+?)\s+([0-9a-f]+)\]\s+(.+)$", re.MULTILINE)
_GIT_PUSH_COUNTING_RE = re.compile(
    r"^(Enumerating|Counting|Compressing|Writing|Total)\s"
    r"|^remote:\s*(Enumerating|Counting|Compressing|Resolving deltas|Total|$)",
)
_GIT_ERROR_RE = re.compile(r"^(error|fatal|CONFLICT|MERGE_MSG|hint:)", re.IGNORECASE)


class GitOperationCompressor:
    """Compress git add/commit/push/pull output for both success and failure."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        if is_failure:
            return self._compress_failure(stdout)
        return self._compress_success(stdout)

    def _compress_success(self, stdout: str) -> str | None:
        lines = stdout.splitlines()

        commit_match = _GIT_COMMIT_SUCCESS_RE.search(stdout)
        if commit_match:
            branch, short_hash, message = commit_match.groups()
            file_changes = [
                line.strip()
                for line in lines
                if line.strip()
                and not _GIT_COMMIT_SUCCESS_RE.match(line)
                and ("file changed" in line or "insertion" in line or "deletion" in line)
            ]
            summary = f"[{branch} {short_hash}] {message}"
            if file_changes:
                summary += f"\n{file_changes[0]}"
            return summary if len(summary) < len(stdout) else None

        if any(_GIT_PUSH_COUNTING_RE.match(line) for line in lines):
            meaningful = [line for line in lines if not _GIT_PUSH_COUNTING_RE.match(line) and line.strip()]
            if meaningful:
                compressed = "\n".join(meaningful)
                return compressed if len(compressed) < len(stdout) * 0.7 else None

        return None

    def _compress_failure(self, stdout: str) -> str | None:
        lines = stdout.splitlines()
        result = [line for line in lines if line.strip() and not _GIT_PUSH_COUNTING_RE.match(line.strip())]
        compressed = "\n".join(result)
        return compressed if len(compressed) < len(stdout) * 0.9 else None


# ---------------------------------------------------------------------------
# Ls Compressor
# ---------------------------------------------------------------------------

_LS_LONG_LINE_RE = re.compile(
    r"^[dlcbps-][rwxsStT-]{9}[+@.]?\s+"
    r"\d+\s+"
    r"\S+\s+"
    r"\S+\s+"
    r"[\d,]+\s+"
    r"(?:\w+\s+\d+\s+[\d:]+|\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+"
    r"(.+)$"
)
_LS_TOTAL_RE = re.compile(r"^total \d+$")


class LsCompressor:
    """Compress ls -la output: extract filenames with type indicators."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        lines = stdout.splitlines()
        if len(lines) < 3:
            return None

        has_long_format = any(_LS_LONG_LINE_RE.match(line) for line in lines[:5])
        if not has_long_format:
            return None

        result: list[str] = []
        for line in lines:
            if _LS_TOTAL_RE.match(line.strip()):
                continue
            match = _LS_LONG_LINE_RE.match(line)
            if match:
                name = match.group(1)
                result.append(f"{name}/" if line[0] == "d" else name)
            elif line.strip():
                result.append(line.strip())

        if not result:
            return None
        compressed = "\n".join(result)
        return compressed if len(compressed) < len(stdout) * 0.7 else None


# ---------------------------------------------------------------------------
# Test Compressor (pytest/jest/cargo test/go test)
# ---------------------------------------------------------------------------

_PYTEST_SUMMARY_RE = re.compile(r"=+\s*(\d+\s+passed.*?)\s*=+", re.IGNORECASE)
_JEST_SUMMARY_RE = re.compile(r"Tests:\s+(.+)")
_CARGO_TEST_SUMMARY_RE = re.compile(r"^test result: ok\.\s+(.+)$", re.MULTILINE)
_GO_TEST_SUMMARY_RE = re.compile(r"^(ok|FAIL)\s+(.+)$", re.MULTILINE)
_TEST_NOISE_RE = re.compile(
    r"^(platform .+|rootdir: .+|plugins: .+|collected \d+ items?$|cachedir: .+|configfile: .+)",
    re.IGNORECASE,
)
_TEST_PASSED_RE = re.compile(r"^.+::.+\s+PASSED\s*$")


class TestCompressor:
    """Compress test runner output for both success and failure scenarios."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        if is_failure:
            return self._compress_failure(stdout)
        return self._compress_success(stdout)

    def _compress_success(self, stdout: str) -> str | None:
        pytest_match = _PYTEST_SUMMARY_RE.search(stdout)
        if pytest_match:
            return pytest_match.group(1).strip()

        jest_match = _JEST_SUMMARY_RE.search(stdout)
        if jest_match and "failed" not in jest_match.group(1).lower():
            return jest_match.group(1).strip()

        cargo_match = _CARGO_TEST_SUMMARY_RE.search(stdout)
        if cargo_match:
            return f"test result: ok. {cargo_match.group(1)}"

        go_matches = _GO_TEST_SUMMARY_RE.findall(stdout)
        if go_matches and all(status == "ok" for status, _ in go_matches):
            compressed = "\n".join(f"ok {pkg}" for _, pkg in go_matches)
            return compressed if len(compressed) < len(stdout) * 0.5 else None

        return None

    def _compress_failure(self, stdout: str) -> str | None:
        """Strip noise (platform, PASSED lines), keep FAILED/ERROR/summary."""
        lines = stdout.splitlines()
        result = [line for line in lines if not _TEST_NOISE_RE.match(line.strip()) and not _TEST_PASSED_RE.match(line)]
        compressed = "\n".join(result)
        return compressed if len(compressed) < len(stdout) * 0.9 else None


# ---------------------------------------------------------------------------
# Package Install Compressor (npm/bun/pip/uv)
# ---------------------------------------------------------------------------

_NPM_ADDED_RE = re.compile(r"^added \d+ packages?.+$", re.MULTILINE)
_NPM_AUDIT_RE = re.compile(r"^found \d+ vulnerabilit\w*.*$", re.MULTILINE)
_PIP_SUCCESS_RE = re.compile(r"^Successfully installed (.+)$", re.MULTILINE)
_UV_INSTALLED_RE = re.compile(r"^(Installed|Resolved) \d+ package", re.MULTILINE)
_PROGRESS_LINE_RE = re.compile(r"^\s*(Collecting|Downloading|Using cached|Building|Preparing|Installing build)")
_NPM_WARN_RE = re.compile(r"^npm warn", re.MULTILINE)


class PackageInstallCompressor:
    """Compress package install output: keep summary/errors, remove progress."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        if is_failure:
            return self._compress_failure(stdout)
        return self._compress_success(stdout)

    def _compress_success(self, stdout: str) -> str | None:
        npm_added = _NPM_ADDED_RE.search(stdout)
        if npm_added:
            parts = [npm_added.group(0)]
            audit = _NPM_AUDIT_RE.search(stdout)
            if audit:
                parts.append(audit.group(0))
            warn_count = len(_NPM_WARN_RE.findall(stdout))
            if warn_count > 0:
                parts.append(f"({warn_count} warnings)")
            compressed = " ".join(parts)
            return compressed if len(compressed) < len(stdout) else None

        pip_match = _PIP_SUCCESS_RE.search(stdout)
        if pip_match:
            packages = pip_match.group(1)
            pkg_count = len(packages.split())
            compressed = f"Successfully installed {pkg_count} packages"
            return compressed if len(compressed) < len(stdout) else None

        uv_match = _UV_INSTALLED_RE.search(stdout)
        if uv_match:
            lines = stdout.splitlines()
            summary_lines = [line for line in lines if not _PROGRESS_LINE_RE.match(line) and line.strip()]
            if summary_lines:
                compressed = "\n".join(summary_lines[-3:])
                return compressed if len(compressed) < len(stdout) * 0.7 else None

        return None

    def _compress_failure(self, stdout: str) -> str | None:
        """Strip download/progress lines, keep everything else."""
        lines = stdout.splitlines()
        result = [line for line in lines if not _PROGRESS_LINE_RE.match(line)]
        compressed = "\n".join(result)
        return compressed if len(compressed) < len(stdout) * 0.9 else None


# ---------------------------------------------------------------------------
# Docker Build Compressor
# ---------------------------------------------------------------------------

_DOCKER_EXTRACT_RE = re.compile(r"^#\d+\s+(extracting|sha256:)")
_DOCKER_RESOLVE_RE = re.compile(r"^#\d+\s+resolve ")


class DockerBuildCompressor:
    """Compress docker build output: strip extracting/sha256 noise, keep steps and errors."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        lines = stdout.splitlines()
        result = [
            line
            for line in lines
            if line.strip()
            and not _DOCKER_EXTRACT_RE.match(line.strip())
            and not _DOCKER_RESOLVE_RE.match(line.strip())
        ]
        if not result:
            return None
        compressed = "\n".join(result)
        return compressed if len(compressed) < len(stdout) * 0.9 else None


# ---------------------------------------------------------------------------
# Build Tool Compressor (cargo build / make / cmake)
# ---------------------------------------------------------------------------

_BUILD_COMPILING_RE = re.compile(
    r"^\s*(Compiling|Downloading|Downloaded|Updating|Unpacking)\s+\S+\s+v\d",
    re.IGNORECASE,
)


class BuildToolCompressor:
    """Compress build tool output (cargo build, make, etc.): strip Compiling noise on failure."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        if not is_failure:
            return None
        lines = stdout.splitlines()
        result = [line for line in lines if not _BUILD_COMPILING_RE.match(line)]
        if not result:
            return None
        compressed = "\n".join(result)
        return compressed if len(compressed) < len(stdout) * 0.8 else None


# ---------------------------------------------------------------------------
# Compiler Error Compressor (tsc / eslint)
# ---------------------------------------------------------------------------

_TSC_ERROR_RE = re.compile(r"^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)$")
_ESLINT_ERROR_RE = re.compile(r"^\s+(\d+):(\d+)\s+(error|warning)\s+(.+?)\s+(@.+|[\w-]+)$")
_ESLINT_FILE_RE = re.compile(r"^(/[^\s]+|C:\\[^\s]+|.*\.ts|.*\.js|.*\.tsx|.*\.jsx)$")


class CompilerErrorCompressor:
    """Compress compiler/linter output: group by file, extract core error info, drop code snippets."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        if not is_failure:
            return None

        lines = stdout.splitlines()
        is_eslint = any(_ESLINT_ERROR_RE.match(line) for line in lines[:50])
        if is_eslint:
            return self._compress_eslint(lines, stdout)
        return self._compress_tsc(lines, stdout)

    def _compress_tsc(self, lines: list[str], original_stdout: str) -> str | None:
        errors_by_file: dict[str, list[str]] = {}
        error_counts: dict[str, int] = {}
        total_errors = 0

        for line in lines:
            match = _TSC_ERROR_RE.match(line)
            if match:
                file_path, line_num, _, severity, code, message = match.groups()
                if severity == "warning":
                    continue
                if file_path not in errors_by_file:
                    errors_by_file[file_path] = []
                errors_by_file[file_path].append(f"Line {line_num}: [{code}] {message}")
                error_counts[code] = error_counts.get(code, 0) + 1
                total_errors += 1

        if total_errors == 0:
            return None
        return self._format_result(errors_by_file, error_counts, total_errors, original_stdout)

    def _compress_eslint(self, lines: list[str], original_stdout: str) -> str | None:
        errors_by_file: dict[str, list[str]] = {}
        error_counts: dict[str, int] = {}
        total_errors = 0
        current_file = None

        for line in lines:
            file_match = _ESLINT_FILE_RE.match(line.strip())
            if file_match:
                current_file = file_match.group(1)
                continue
            match = _ESLINT_ERROR_RE.match(line)
            if match and current_file:
                line_num, _, severity, message, rule = match.groups()
                if severity == "warning":
                    continue
                if current_file not in errors_by_file:
                    errors_by_file[current_file] = []
                errors_by_file[current_file].append(f"Line {line_num}: [{rule}] {message}")
                error_counts[rule] = error_counts.get(rule, 0) + 1
                total_errors += 1

        if total_errors == 0:
            return None
        return self._format_result(errors_by_file, error_counts, total_errors, original_stdout)

    def _format_result(
        self,
        errors_by_file: dict[str, list[str]],
        error_counts: dict[str, int],
        total_errors: int,
        original_stdout: str,
    ) -> str | None:
        result = ["[System Note: Compiler output aggregated for clarity]"]
        displayed_errors = 0
        max_errors_to_display = 20

        for file_path, errors in errors_by_file.items():
            if displayed_errors >= max_errors_to_display:
                break
            result.append(f"{file_path}:")
            for err in errors:
                if displayed_errors >= max_errors_to_display:
                    break
                result.append(f"  - {err}")
                displayed_errors += 1

        if total_errors > max_errors_to_display:
            result.append(
                f"\n[System Note: Showing first {max_errors_to_display} errors "
                f"out of {total_errors}. Fix these and run again.]"
            )

        top_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        top_errors_str = ", ".join(f"{code} ({count})" for code, count in top_errors)
        result.append(
            f"\nSummary: Found {total_errors} errors across {len(errors_by_file)} files. Top errors: {top_errors_str}."
        )

        compressed = "\n".join(result)
        return compressed if len(compressed) < len(original_stdout) * 0.95 else None


# ---------------------------------------------------------------------------
# Log Deduplication Compressor
# ---------------------------------------------------------------------------

_LOG_TIMESTAMP_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}[.,]?\d*\s*")
_LOG_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_LOG_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")
_LOG_NUM_RE = re.compile(r"\b\d{4,}\b")
_LOG_PATH_RE = re.compile(r"/[\w./\-]+")


class LogCompressor:
    """Compress massive repetitive logs: normalize dynamic variables and deduplicate."""

    def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
        lines = stdout.splitlines()
        if len(lines) < 100:
            return None

        error_counts: dict[str, int] = {}
        warn_counts: dict[str, int] = {}
        info_counts: dict[str, int] = {}
        unique_errors: list[str] = []
        unique_warnings: list[str] = []

        for line in lines:
            line_lower = line.lower()
            normalized = self._normalize(line)
            if not normalized:
                continue
            if any(
                k in line_lower
                for k in (
                    "error",
                    "fatal",
                    "panic",
                    "critical",
                    "alert",
                    "emerg",
                    "severe",
                    "exception",
                )
            ):
                if normalized not in error_counts:
                    unique_errors.append(line)
                    error_counts[normalized] = 0
                error_counts[normalized] += 1
            elif any(k in line_lower for k in ("warn", "notice")):
                if normalized not in warn_counts:
                    unique_warnings.append(line)
                    warn_counts[normalized] = 0
                warn_counts[normalized] += 1
            else:
                info_counts[normalized] = info_counts.get(normalized, 0) + 1

        total_errors = sum(error_counts.values())
        total_warnings = sum(warn_counts.values())
        total_info = sum(info_counts.values())

        unique_total = len(error_counts) + len(warn_counts) + len(info_counts)
        if unique_total > len(lines) * 0.5:
            return None

        result = [
            "[System Note: Detected massive repetitive logs. Auto-deduplicated.]",
            "Log Summary:",
        ]
        if total_errors > 0:
            result.append(f"  [error] {total_errors} errors ({len(error_counts)} unique)")
        if total_warnings > 0:
            result.append(f"  [warn] {total_warnings} warnings ({len(warn_counts)} unique)")
        if total_info > 0:
            result.append(f"  [info] {total_info} info messages")
        result.append("")

        if unique_errors:
            result.append("[ERRORS]")
            sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
            for normalized, count in sorted_errors[:10]:
                original = next(
                    (e for e in unique_errors if self._normalize(e) == normalized),
                    normalized,
                )
                result.append(f"  [×{count}] {original}" if count > 1 else f"  {original}")
            if len(sorted_errors) > 10:
                result.append(f"  ... +{len(sorted_errors) - 10} more unique errors")
            result.append("")

        if unique_warnings:
            result.append("[WARNINGS]")
            sorted_warns = sorted(warn_counts.items(), key=lambda x: x[1], reverse=True)
            for normalized, count in sorted_warns[:5]:
                original = next(
                    (w for w in unique_warnings if self._normalize(w) == normalized),
                    normalized,
                )
                result.append(f"  [×{count}] {original}" if count > 1 else f"  {original}")
            if len(sorted_warns) > 5:
                result.append(f"  ... +{len(sorted_warns) - 5} more unique warnings")

        compressed = "\n".join(result).strip()
        return compressed if len(compressed) < len(stdout) else None

    def _normalize(self, line: str) -> str:
        normalized = _LOG_TIMESTAMP_RE.sub("", line)
        normalized = _LOG_UUID_RE.sub("<UUID>", normalized)
        normalized = _LOG_HEX_RE.sub("<HEX>", normalized)
        normalized = _LOG_NUM_RE.sub("<NUM>", normalized)
        normalized = _LOG_PATH_RE.sub("<PATH>", normalized)
        return normalized.strip()
