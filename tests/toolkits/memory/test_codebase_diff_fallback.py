"""Tests for codebase memory large diff fallback suite."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.codebase_diff_fallback import (
    CodebaseDiffFallbackSuite,
    DiffCategory,
    DiffFallbackVerdict,
    DiffFileEntry,
    DiffPathClassifier,
    DiffVolumeTier,
    LargeDiffFallbackConfig,
    LargeDiffFallbackPipeline,
)


def test_path_classifier_categories() -> None:
    """Verifies that file paths are accurately categorized."""
    classifier = DiffPathClassifier()

    assert classifier.classify_path("package-lock.json") == DiffCategory.LOCKFILE
    assert classifier.classify_path("pnpm-lock.yaml") == DiffCategory.LOCKFILE
    assert classifier.classify_path("Cargo.lock") == DiffCategory.LOCKFILE
    assert classifier.classify_path("dist/bundle.min.js") == DiffCategory.GENERATED
    assert classifier.classify_path("src/proto_pb2.py") == DiffCategory.GENERATED
    assert classifier.classify_path("assets/hero.svg") == DiffCategory.ASSET_BINARY
    assert classifier.classify_path("docs/ARCHITECTURE.md") == DiffCategory.DOCUMENTATION
    assert classifier.classify_path("README.md") == DiffCategory.DOCUMENTATION
    assert classifier.classify_path(".github/workflows/ci.yml") == DiffCategory.CONFIG_INFRA
    assert classifier.classify_path("src/components/Button.tsx") == DiffCategory.CORE_CODE
    assert classifier.classify_path("app/services/memory.py") == DiffCategory.CORE_CODE

    assert classifier.extract_top_directory("src/components/Button.tsx") == "src"
    assert classifier.extract_top_directory("standalone.py") == "."


def test_tier_evaluation_micro() -> None:
    """Verifies Micro tier behavior: full fidelity retained for small diffs."""
    files: list[DiffFileEntry] = [
        DiffFileEntry(
            path="src/main.py",
            additions=50,
            deletions=20,
            patch_snippet="def main():\n    return 42",
        ),
        DiffFileEntry(
            path="tests/test_main.py",
            additions=30,
            deletions=5,
            patch_snippet="def test_main(): assert main() == 42",
        ),
    ]

    pipeline = LargeDiffFallbackPipeline()
    verdict: DiffFallbackVerdict = pipeline.process(files, commit_message="feat: small fix")

    assert verdict.tier == DiffVolumeTier.MICRO
    assert not verdict.is_truncated
    assert verdict.total_files == 2
    assert verdict.total_additions == 80
    assert verdict.total_deletions == 25
    assert verdict.active_files_count == 2
    assert verdict.filtered_noise_files_count == 0
    assert "src/main.py" in verdict.summary_text
    assert "full_fidelity_ast_retained" in verdict.applied_optimizations


def test_tier_evaluation_moderate_noise_folding() -> None:
    """Verifies Moderate tier behavior: lockfiles and assets folded as noise."""
    files: list[DiffFileEntry] = []
    # 25 core files
    for i in range(25):
        files.append(
            DiffFileEntry(
                path=f"src/module_{i}.py",
                additions=40,
                deletions=10,
                patch_snippet=f"# Change in module {i}",
            )
        )
    # 5 noise files
    files.append(DiffFileEntry(path="pnpm-lock.yaml", additions=800, deletions=400))
    files.append(DiffFileEntry(path="dist/app.min.js", additions=300, deletions=100))
    files.append(DiffFileEntry(path="assets/banner.png", additions=0, deletions=0))

    pipeline = LargeDiffFallbackPipeline()
    verdict: DiffFallbackVerdict = pipeline.process(files)

    assert verdict.tier == DiffVolumeTier.MODERATE
    assert not verdict.is_truncated
    assert verdict.total_files == 28
    assert verdict.active_files_count == 25
    assert verdict.filtered_noise_files_count == 3
    assert "Folded Noise/Generated Files" in verdict.summary_text
    assert "pnpm-lock.yaml" in verdict.summary_text
    assert "noise_filtration_active" in verdict.applied_optimizations


def test_tier_evaluation_large_clustering() -> None:
    """Verifies Large tier behavior: raw patches omitted, directory clustering."""
    files: list[DiffFileEntry] = []
    for i in range(120):
        directory = "backend" if i % 2 == 0 else "frontend"
        files.append(
            DiffFileEntry(
                path=f"{directory}/feature_{i}.py",
                additions=25,
                deletions=10,
                patch_snippet="large snippet to be dropped",
            )
        )

    pipeline = LargeDiffFallbackPipeline()
    verdict: DiffFallbackVerdict = pipeline.process(files, commit_message="refactor: system-wide")

    assert verdict.tier == DiffVolumeTier.LARGE
    assert not verdict.is_truncated
    assert verdict.total_files == 120
    assert len(verdict.directory_aggregates) >= 2
    assert "Architecture Summary" in verdict.summary_text
    assert "Module Clusters" in verdict.summary_text
    assert "directory_level_clustering" in verdict.applied_optimizations


def test_tier_evaluation_massive_fail_safe() -> None:
    """Verifies Massive tier behavior: fail-safe zero-AST topology mode."""
    files: list[DiffFileEntry] = [
        DiffFileEntry(path=f"repo/file_{i}.txt", additions=10, deletions=2)
        for i in range(550)
    ]

    pipeline = LargeDiffFallbackPipeline()
    verdict: DiffFallbackVerdict = pipeline.process(files)

    assert verdict.tier == DiffVolumeTier.MASSIVE
    assert verdict.total_files == 550
    assert verdict.active_files_count == 0
    assert "Fail-Safe Topology Summary" in verdict.summary_text
    assert "massive_fallback_fail_safe" in verdict.applied_optimizations


def test_truncation_detection_declared_count() -> None:
    """Verifies truncation detection when declared file count exceeds received files."""
    files: list[DiffFileEntry] = [
        DiffFileEntry(path=f"src/file_{i}.py", additions=10, deletions=2)
        for i in range(15)
    ]

    pipeline = LargeDiffFallbackPipeline()
    verdict: DiffFallbackVerdict = pipeline.process(
        files,
        declared_total_files=80,  # Missing 65 files
    )

    assert verdict.is_truncated
    assert verdict.tier == DiffVolumeTier.MASSIVE
    assert verdict.truncation_reason is not None
    assert "File list truncated: received 15 of 80" in verdict.truncation_reason
    assert "truncation_guard_activated" in verdict.applied_optimizations


def test_truncation_detection_api_flag() -> None:
    """Verifies truncation detection when API explicitly flags truncation."""
    files: list[DiffFileEntry] = [
        DiffFileEntry(path="src/a.py", additions=5, deletions=1)
    ]

    pipeline = LargeDiffFallbackPipeline()
    verdict: DiffFallbackVerdict = pipeline.process(files, is_api_truncated=True)

    assert verdict.is_truncated
    assert verdict.tier == DiffVolumeTier.MASSIVE
    assert "API explicitly marked file list as truncated" in str(verdict.truncation_reason)


def test_hard_file_cap_guard() -> None:
    """Verifies that reaching hard cap (3000 files) triggers truncation fallback."""
    config = LargeDiffFallbackConfig(hard_file_cap=50)  # Set small cap for test
    files: list[DiffFileEntry] = [
        DiffFileEntry(path=f"file_{i}.py", additions=1, deletions=0)
        for i in range(50)
    ]

    pipeline = LargeDiffFallbackPipeline(config)
    verdict: DiffFallbackVerdict = pipeline.process(files)

    assert verdict.is_truncated
    assert verdict.tier == DiffVolumeTier.MASSIVE
    assert "reached or exceeded hard cap" in str(verdict.truncation_reason)


def test_facade_parse_numstat_line() -> None:
    """Verifies that git numstat lines are correctly parsed into entries."""
    suite = CodebaseDiffFallbackSuite()

    # Regular file
    e1 = suite.parse_numstat_line("45\t12\tsrc/engine/core.py")
    assert e1 is not None
    assert e1.path == "src/engine/core.py"
    assert e1.additions == 45
    assert e1.deletions == 12
    assert e1.category == DiffCategory.CORE_CODE
    assert not e1.is_renamed

    # Binary file with dashes
    e2 = suite.parse_numstat_line("-\t-\tassets/logo.png")
    assert e2 is not None
    assert e2.path == "assets/logo.png"
    assert e2.additions == 0
    assert e2.deletions == 0
    assert e2.category == DiffCategory.ASSET_BINARY

    # Simple rename
    e3 = suite.parse_numstat_line("10\t0\told_utils.py => new_utils.py")
    assert e3 is not None
    assert e3.path == "new_utils.py"
    assert e3.old_path == "old_utils.py"
    assert e3.is_renamed

    # Complex brace rename
    e4 = suite.parse_numstat_line("5\t5\tsrc/{v1 => v2}/api.py")
    assert e4 is not None
    assert e4.path == "src/v2/api.py"
    assert e4.old_path == "src/v1/api.py"
    assert e4.is_renamed


def test_empty_diff_resilience() -> None:
    """Verifies graceful zero-error execution on empty diff input."""
    suite = CodebaseDiffFallbackSuite()
    verdict = suite.process_diff([])

    assert verdict.tier == DiffVolumeTier.MICRO
    assert verdict.total_files == 0
    assert verdict.total_additions == 0
    assert verdict.total_deletions == 0
    assert not verdict.is_truncated
    assert verdict.active_files_count == 0
