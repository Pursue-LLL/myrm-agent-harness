"""Architecture gate: release/core wheel zip contents must not leak manifest source."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_ARCH_DIR))

from harness_packaging.integrity import (  # noqa: E402
    DistributionWheelArtifactError,
    DistributionWheelRole,
    distribution_wheel_artifact_violations,
    verify_distribution_wheel_artifact,
)
from harness_packaging.release import finalize_stripped_release_wheel, manifest_source_paths  # noqa: E402
from distribution_wheel_helpers import (  # noqa: E402
    write_minimal_core_wheel,
    write_minimal_release_wheel,
)


def _assert_wheel_record_matches_archive(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path, "r") as zf:
        record_path = next(name for name in zf.namelist() if name.endswith(".dist-info/RECORD"))
        archive_paths = set(zf.namelist())
        recorded_paths: set[str] = set()

        for line in zf.read(record_path).decode("utf-8").splitlines():
            if not line:
                continue
            path, digest, size_str = line.split(",", 2)
            recorded_paths.add(path)
            if path == record_path:
                assert digest == ""
                assert size_str == ""
                continue
            assert path in archive_paths
            data = zf.read(path)
            assert int(size_str) == len(data)
            assert digest.startswith("sha256=")

        assert recorded_paths == archive_paths


@pytest.mark.architecture
def test_release_wheel_artifact_accepts_stripped_layout(tmp_path: Path) -> None:
    wheel_path = tmp_path / "myrm_agent_harness-0.1.0-py3-none-any.whl"
    write_minimal_release_wheel(wheel_path)
    verify_distribution_wheel_artifact(wheel_path, role=DistributionWheelRole.RELEASE)


@pytest.mark.architecture
def test_release_wheel_artifact_rejects_manifest_py(tmp_path: Path) -> None:
    manifest_paths = manifest_source_paths()
    wheel_path = tmp_path / "myrm_agent_harness-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("myrm_agent_harness/api/__init__.py", "# public")
        zf.writestr(manifest_paths[0], "# secret")

    violations = distribution_wheel_artifact_violations(
        wheel_path,
        role=DistributionWheelRole.RELEASE,
    )
    assert violations
    assert "Manifest .py source must not ship" in violations[0]

    with pytest.raises(DistributionWheelArtifactError, match="Manifest .py source must not ship"):
        verify_distribution_wheel_artifact(wheel_path, role=DistributionWheelRole.RELEASE)


@pytest.mark.architecture
def test_release_wheel_artifact_rejects_debug_map(tmp_path: Path) -> None:
    wheel_path = tmp_path / "myrm_agent_harness-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("myrm_agent_harness/api/__init__.py", "# public")
        zf.writestr("myrm_agent_harness/cli.js.map", "{}")

    with pytest.raises(DistributionWheelArtifactError, match="Debug mapping artifacts"):
        verify_distribution_wheel_artifact(wheel_path, role=DistributionWheelRole.RELEASE)


@pytest.mark.architecture
def test_release_wheel_artifact_rejects_invalid_zip(tmp_path: Path) -> None:
    wheel_path = tmp_path / "myrm_agent_harness-0.1.0-py3-none-any.whl"
    wheel_path.write_bytes(b"not-a-wheel")

    with pytest.raises(DistributionWheelArtifactError, match="Invalid wheel zip"):
        verify_distribution_wheel_artifact(wheel_path, role=DistributionWheelRole.RELEASE)


@pytest.mark.architecture
def test_core_wheel_artifact_accepts_compiled_layout(tmp_path: Path) -> None:
    wheel_path = tmp_path / "myrm_agent_harness_core_linux_x64-0.1.0-cp313-cp313-linux_x86_64.whl"
    write_minimal_core_wheel(wheel_path)
    verify_distribution_wheel_artifact(wheel_path, role=DistributionWheelRole.CORE)


@pytest.mark.architecture
def test_finalize_stripped_release_wheel_strips_and_verifies(tmp_path: Path) -> None:
    manifest_paths = manifest_source_paths()
    wheel_path = tmp_path / "myrm_agent_harness-0.1.0-py3-none-any.whl"
    record_path = "myrm_agent_harness-0.1.0.dist-info/RECORD"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("myrm_agent_harness/api/__init__.py", "# public")
        for manifest_path in manifest_paths[:2]:
            zf.writestr(manifest_path, "# secret")
        zf.writestr(
            record_path,
            "\n".join(
                [
                    "myrm_agent_harness/api/__init__.py,sha256=deadbeef,7",
                    f"{manifest_paths[0]},sha256=deadbeef,8",
                    f"{manifest_paths[1]},sha256=deadbeef,8",
                    f"{record_path},,",
                ]
            )
            + "\n",
        )

    result = finalize_stripped_release_wheel(wheel_path, in_place=True)
    assert result == wheel_path

    with zipfile.ZipFile(wheel_path, "r") as zf:
        names = zf.namelist()
    assert "myrm_agent_harness/api/__init__.py" in names
    assert manifest_paths[0] not in names
    assert manifest_paths[1] not in names
    _assert_wheel_record_matches_archive(wheel_path)


@pytest.mark.architecture
def test_finalize_stripped_release_wheel_rebuilds_record_with_dist_info(tmp_path: Path) -> None:
    manifest_paths = manifest_source_paths()
    wheel_path = tmp_path / "myrm_agent_harness-0.1.0-py3-none-any.whl"
    record_path = "myrm_agent_harness-0.1.0.dist-info/RECORD"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("myrm_agent_harness/api/__init__.py", "# public")
        zf.writestr(manifest_paths[0], "# secret")
        zf.writestr(
            record_path,
            "\n".join(
                [
                    "myrm_agent_harness/api/__init__.py,sha256=deadbeef,7",
                    f"{manifest_paths[0]},sha256=deadbeef,8",
                    f"{record_path},,",
                ]
            )
            + "\n",
        )

    finalize_stripped_release_wheel(wheel_path, in_place=True)
    _assert_wheel_record_matches_archive(wheel_path)


@pytest.mark.architecture
def test_core_wheel_artifact_rejects_manifest_py_and_missing_compiled(tmp_path: Path) -> None:
    manifest_paths = manifest_source_paths()
    wheel_path = tmp_path / "myrm_agent_harness_core_linux_x64-0.1.0-cp313-cp313-linux_x86_64.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr(manifest_paths[0], "# secret")

    violations = distribution_wheel_artifact_violations(
        wheel_path,
        role=DistributionWheelRole.CORE,
    )
    assert any("Manifest .py source must not ship" in item for item in violations)
    assert any("Missing Nuitka .so/.pyd" in item for item in violations)
