"""Architecture guard: ruff S (security / bandit) rules must stay active.

Verifies that pyproject.toml keeps the S rule-set selected and noisy
false-positive rules suppressed, so every save catches real security issues
(pickle, eval, exec, chmod, SSL, …) without drowning in noise.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _find_ruff() -> str:
    venv_ruff = _REPO_ROOT / ".venv" / "bin" / "ruff"
    if venv_ruff.is_file():
        return str(venv_ruff)
    system_ruff = shutil.which("ruff")
    if system_ruff:
        return system_ruff
    pytest.skip("ruff not found in venv or PATH")
    return ""  # unreachable, satisfies type checker

_REQUIRED_NOISE_SUPPRESSIONS = frozenset(
    {
        "S101",  # assert (runtime invariant checks)
        "S105",  # hardcoded-password-string
        "S106",  # hardcoded-password-func-arg
        "S107",  # hardcoded-password-default
        "S108",  # hardcoded-temp-file (/tmp safe in sandbox)
        "S110",  # try-except-pass (best-effort pattern)
        "S112",  # try-except-continue
        "S311",  # non-cryptographic random (sampling/ID)
        "S324",  # hashlib-insecure (content hash, not crypto)
        "S603",  # subprocess-without-shell-equals-true (code-exec tool)
        "S607",  # start-process-with-partial-path
        "S608",  # hardcoded-sql (local SQLite)
    }
)


def _load_ruff_lint() -> dict:
    with _PYPROJECT.open("rb") as f:
        data = tomllib.load(f)
    return data["tool"]["ruff"]["lint"]


@pytest.mark.architecture
class TestRuffSecurityConfig:
    """Validate ruff security rule configuration in pyproject.toml."""

    def test_security_ruleset_selected(self) -> None:
        lint = _load_ruff_lint()
        select: list[str] = lint["select"]
        assert "S" in select, f"ruff select must include 'S' (security rules), got: {select}"

    def test_noise_suppressions_complete(self) -> None:
        lint = _load_ruff_lint()
        ignored: set[str] = {rule for rule in lint.get("ignore", []) if rule.startswith("S")}
        missing = _REQUIRED_NOISE_SUPPRESSIONS - ignored
        assert not missing, (
            f"Missing required noise suppressions in ruff ignore: {sorted(missing)}. "
            "These are validated false-positives in an agent framework."
        )

    def test_no_overly_broad_suppression(self) -> None:
        """S rules should never be blanket-suppressed for the entire project."""
        lint = _load_ruff_lint()
        ignored = lint.get("ignore", [])
        broad_suppressions = [r for r in ignored if r == "S" or (r.startswith("S") and len(r) == 2)]
        assert not broad_suppressions, (
            f"Overly broad S-rule suppression detected: {broad_suppressions}. "
            "Suppress individual rules, not the entire category."
        )

    def test_tests_dir_allows_assert(self) -> None:
        lint = _load_ruff_lint()
        per_file = lint.get("per-file-ignores", {})
        tests_ignores = per_file.get("tests/**/*.py", [])
        assert "S101" in tests_ignores, "tests/ must allow assert (S101) in per-file-ignores"

    def test_config_syntax_valid(self) -> None:
        ruff = _find_ruff()
        result = subprocess.run(
            [ruff, "check", "--select", "S", "--no-fix", "-q", str(_REPO_ROOT / "src")],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=60,
        )
        assert result.returncode in (0, 1), (
            f"ruff failed with unexpected returncode {result.returncode}: {result.stderr}"
        )

    def test_security_scan_detects_known_issues(self) -> None:
        """S rules must detect at least 1 real security issue in the harness source."""
        ruff = _find_ruff()
        result = subprocess.run(
            [ruff, "check", "--select", "S", "--statistics", "--no-fix", str(_REPO_ROOT / "src")],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=60,
        )
        stats_lines = [
            line for line in result.stdout.strip().splitlines()
            if line.strip() and not line.startswith("Found")
        ]
        assert len(stats_lines) >= 1, (
            "ruff S rules should detect at least 1 security diagnostic. "
            f"Got: {result.stdout}"
        )

    def test_suppressed_rules_absent_from_output(self) -> None:
        """Suppressed noise rules must not appear in ruff output."""
        ruff = _find_ruff()
        result = subprocess.run(
            [ruff, "check", "--select", "S", "--no-fix", str(_REPO_ROOT / "src")],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=60,
        )
        output = result.stdout + result.stderr
        found_noise: list[str] = []
        for rule in _REQUIRED_NOISE_SUPPRESSIONS:
            if f" {rule} " in output or f"[{rule}]" in output:
                found_noise.append(rule)
        assert not found_noise, (
            f"Suppressed noise rules still appearing in ruff output: {found_noise}. "
            "Check that pyproject.toml ignore list is effective."
        )
