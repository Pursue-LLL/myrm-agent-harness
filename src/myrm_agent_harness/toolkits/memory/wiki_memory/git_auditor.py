# [POS] toolkits/memory/wiki_memory/git_auditor.py
# [INPUT] pathlib.Path, types.WikiAuditCommit
# [OUTPUT] WikiGitAuditor

"""Thread-safe Git version control auditor for Markdown memory repositories."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

from .types import WikiAuditCommit


class WikiGitAuditor:
    """Provides atomic Git versioning, log auditing, and rollback for memory wikis."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root
        self._lock = threading.RLock()
        self._git_bin: str | None = shutil.which("git")
        self._in_memory_log: list[WikiAuditCommit] = []

    @property
    def is_git_available(self) -> bool:
        """Return True if git binary is discovered on the host system."""
        return self._git_bin is not None

    def init_repo(self) -> bool:
        """Initialize Git repository if not already present."""
        if not self._git_bin:
            return False

        with self._lock:
            self._repo_root.mkdir(parents=True, exist_ok=True)
            git_dir = self._repo_root / ".git"
            if not git_dir.exists():
                self._run_git(["init", "--quiet"])
                self._run_git(["config", "user.name", "Myrm Memory Auditor"])
                self._run_git(["config", "user.email", "auditor@myrm.local"])
                self._run_git(["config", "commit.gpgsign", "false"])
            return True

    def commit_change(
        self,
        file_paths: list[Path],
        message: str,
        author: str = "Myrm Memory Auditor",
    ) -> WikiAuditCommit | None:
        """Stage specified memory files and produce an atomic Git commit record."""
        now = time.time()
        relative_paths = [
            str(p.relative_to(self._repo_root) if p.is_absolute() else p)
            for p in file_paths
        ]

        if not self._git_bin:
            # Fallback mock commit record when git binary is not installed
            fallback_commit = WikiAuditCommit(
                commit_hash=f"fallback_{int(now * 1000)}",
                message=message,
                timestamp=now,
                author=author,
                files_changed=relative_paths,
            )
            self._in_memory_log.insert(0, fallback_commit)
            return fallback_commit

        with self._lock:
            self.init_repo()
            # Stage files
            add_args = ["add", *relative_paths]
            res_add = self._run_git(add_args)
            if res_add.returncode != 0:
                return None

            # Commit changes
            commit_args = [
                "commit",
                "--no-gpg-sign",
                "-m",
                message,
                f"--author={author} <auditor@myrm.local>",
            ]
            res_commit = self._run_git(commit_args)
            if res_commit.returncode != 0:
                # Might be clean working tree (no changes)
                return None

            # Obtain commit hash
            rev_res = self._run_git(["rev-parse", "HEAD"])
            commit_hash = rev_res.stdout.strip() if rev_res.returncode == 0 else f"git_{int(now)}"

            record = WikiAuditCommit(
                commit_hash=commit_hash,
                message=message,
                timestamp=now,
                author=author,
                files_changed=relative_paths,
            )
            self._in_memory_log.insert(0, record)
            return record

    def get_history(self, limit: int = 20) -> list[WikiAuditCommit]:
        """Retrieve recent Git commit audit history."""
        if not self._git_bin:
            return self._in_memory_log[:limit]

        with self._lock:
            # Format: hash|timestamp|author|message
            args = ["log", f"-n{limit}", "--pretty=format:%H|%at|%an|%s"]
            res = self._run_git(args)
            if res.returncode != 0 or not res.stdout.strip():
                return self._in_memory_log[:limit]

            commits: list[WikiAuditCommit] = []
            for line in res.stdout.strip().splitlines():
                parts = line.split("|", 3)
                if len(parts) == 4:
                    chash, ts_str, author, msg = parts
                    try:
                        ts = float(ts_str)
                    except ValueError:
                        ts = time.time()
                    commits.append(
                        WikiAuditCommit(
                            commit_hash=chash,
                            message=msg,
                            timestamp=ts,
                            author=author,
                            files_changed=[],
                        )
                    )
            return commits

    def revert_commit(self, commit_hash: str) -> bool:
        """Revert the specified commit to roll back hallucinated or erroneous memory updates."""
        if not self._git_bin:
            return False

        with self._lock:
            args = ["revert", "--no-edit", "--no-gpg-sign", commit_hash]
            res = self._run_git(args)
            return res.returncode == 0

    def _run_git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Execute git command within repo root under thread safety."""
        env = {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
        }
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=5.0,
                env=env,
            )
        except Exception:
            return subprocess.CompletedProcess(
                args=["git", *args],
                returncode=1,
                stdout="",
                stderr="execution_error_or_timeout",
            )

