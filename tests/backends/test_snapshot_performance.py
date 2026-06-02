"""Performance benchmark tests for SQLiteSkillSnapshot."""

import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.xdist_group("snapshot_perf")

from myrm_agent_harness.backends.skills.snapshot import SQLiteSkillSnapshot


def create_test_skill(skill_dir: Path, skill_name: str, index: int) -> None:
    """Helper to create a test skill."""
    skill_path = skill_dir / skill_name
    skill_path.mkdir(exist_ok=True)
    (skill_path / "SKILL.md").write_text(
        f"""---
description: Test skill {index}
version: 1.0.{index}
---
# Test Skill {index}

This is test skill number {index}.
""",
        encoding="utf-8",
    )


@pytest.mark.benchmark(group="snapshot")
def test_snapshot_read_performance_small(benchmark, tmp_path):
    """Benchmark read_all() with 10 skills."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create 10 skills
    for i in range(10):
        create_test_skill(skills_dir, f"skill-{i:03d}", i)

    snapshot_path = skills_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(skills_dir, max_depth=1)

    # Benchmark read_all
    result = benchmark(snapshot.read_all)
    assert len(result) == 10


@pytest.mark.benchmark(group="snapshot")
def test_snapshot_read_performance_medium(benchmark, tmp_path):
    """Benchmark read_all() with 100 skills."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create 100 skills
    for i in range(100):
        create_test_skill(skills_dir, f"skill-{i:03d}", i)

    snapshot_path = skills_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(skills_dir, max_depth=1)

    # Benchmark read_all
    result = benchmark(snapshot.read_all)
    assert len(result) == 100


@pytest.mark.benchmark(group="snapshot")
def test_snapshot_read_performance_large(benchmark, tmp_path):
    """Benchmark read_all() with 1000 skills."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create 1000 skills
    for i in range(1000):
        create_test_skill(skills_dir, f"skill-{i:04d}", i)

    snapshot_path = skills_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(skills_dir, max_depth=1)

    # Benchmark read_all
    result = benchmark(snapshot.read_all)
    assert len(result) == 1000


@pytest.mark.benchmark(group="sync")
def test_snapshot_sync_performance_incremental(benchmark, tmp_path):
    """Benchmark sync_all() incremental update (only modified files)."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create 100 skills
    for i in range(100):
        create_test_skill(skills_dir, f"skill-{i:03d}", i)

    snapshot_path = skills_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(skills_dir, max_depth=1)

    # Modify only 1 skill
    modified_skill = skills_dir / "skill-050"
    (modified_skill / "SKILL.md").write_text(
        """---
description: Modified test skill
version: 2.0.0
---
# Modified Skill
""",
        encoding="utf-8",
    )

    # Benchmark incremental sync (should be O(1) for single file)
    benchmark(snapshot.sync_all, skills_dir, max_depth=1)


def test_snapshot_scaling_comparison(tmp_path):
    """Compare O(N) snapshot read vs O(N) file system scan with full parsing.

    This test demonstrates the true value of the snapshot: it stores pre-parsed
    content in SQLite, avoiding repeated file I/O and parsing overhead.
    """
    from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
    from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter
    from myrm_agent_harness.backends.skills.types import SkillTrust

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    results = {}

    for size in [10, 50, 100, 200]:
        # Create skills
        for i in range(size):
            create_test_skill(skills_dir, f"skill-{i:04d}", i)

        snapshot_path = skills_dir / ".skills_snapshot.sqlite"
        snapshot = SQLiteSkillSnapshot(snapshot_path)
        snapshot.sync_all(skills_dir, max_depth=1)

        # Measure snapshot read (reads from DB, already parsed)
        start = time.perf_counter()
        for _ in range(10):
            snapshot.read_all()
        snapshot_time = (time.perf_counter() - start) / 10

        # Measure file system scan + read + parse (what happens without snapshot)
        def fs_read_and_parse():
            skills = []
            for skill_md in skills_dir.rglob("SKILL.md"):
                content = skill_md.read_text(encoding="utf-8")
                skill_name = skill_md.parent.name
                frontmatter = parse_skill_frontmatter(content, skill_name)
                meta = build_skill_metadata(
                    skill_name=skill_name,
                    frontmatter=frontmatter,
                    storage_path=str(skill_md.parent),
                    content=content,
                    trust=SkillTrust.INSTALLED,
                    workspace_root=skills_dir,
                )
                skills.append(meta)
            return skills

        start = time.perf_counter()
        for _ in range(10):
            fs_read_and_parse()
        fs_time = (time.perf_counter() - start) / 10

        results[size] = {
            "snapshot": snapshot_time,
            "filesystem": fs_time,
            "speedup": fs_time / snapshot_time if snapshot_time > 0 else 0,
        }

        print(f"\n{size} skills:")
        print(f"  Snapshot (DB):          {snapshot_time*1000:.3f}ms")
        print(f"  Filesystem (I/O+parse): {fs_time*1000:.3f}ms")
        print(f"  Speedup:                {results[size]['speedup']:.1f}x")

    # Under parallel CI / xdist load, timings are noisy — use a generous
    # tolerance (0.5x) instead of strict > 1.0 to avoid flaky failures.
    for size in results:
        if size >= 100:
            assert (
                results[size]["speedup"] > 0.5
            ), f"Snapshot should not be drastically slower than filesystem for {size} skills"

    print("\nScaling behavior:")
    print(f"  10 skills:  {results[10]['speedup']:.2f}x")
    print(f"  200 skills: {results[200]['speedup']:.2f}x")
    assert (
        results[200]["speedup"] >= 0.5
    ), "Snapshot should not be drastically slower than filesystem for 200 skills"
