#!/usr/bin/env python3
"""Build and upload rc1 PyPI wheels locally without paid macOS/Windows CI runners.

Builds:
- darwin-arm64 core wheel (native on Apple Silicon Mac)
- linux-x64 core wheel (Docker linux/amd64 when not already on Linux x64)
- stripped release wheel

Requires ``uv sync --group build --group dev`` and Docker for cross-platform linux-x64
builds from macOS. Upload uses ``twine`` with ``TWINE_USERNAME=__token__`` and
``TWINE_PASSWORD=<PyPI API token>``.

Usage::

    uv sync --group build --group dev
    uv run python scripts/publish_pypi_rc1.py --upload-dir pypi-upload
    TWINE_PASSWORD=... uv run python scripts/publish_pypi_rc1.py --upload
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.platforms import PUBLISH_PLATFORMS  # noqa: E402
from harness_packaging.version import read_harness_version  # noqa: E402
from scripts.validate_pypi_wheels import validate_upload_dir  # noqa: E402
from scripts.verify_pypi_publish import verify_published  # noqa: E402

_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python"
_LINUX_X64 = "linux-x64"
_DARWIN_ARM64 = "darwin-arm64"


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=cwd or _REPO_ROOT)


def _require_venv_python() -> Path:
    if not _VENV_PYTHON.is_file():
        msg = "Missing .venv/bin/python — run: uv sync --group build --group dev"
        raise SystemExit(msg)
    return _VENV_PYTHON


def _build_core_wheel(python: Path, platform_key: str) -> Path:
    _run([str(python), "scripts/build_core.py", "--platform", platform_key, "--wheel"])
    wheel_dir = _REPO_ROOT / "build" / "core" / "wheels" / platform_key
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        msg = f"No core wheel produced for {platform_key} in {wheel_dir}"
        raise SystemExit(msg)
    return wheels[-1]


def _build_linux_x64_in_docker() -> Path:
    if shutil.which("docker") is None:
        msg = "docker is required to build linux-x64 wheels from non-Linux-x64 hosts"
        raise SystemExit(msg)
    repo = _REPO_ROOT.resolve()
    script = (
        "apt-get update -qq && apt-get install -y -qq git >/dev/null && "
        "pip install -q uv && "
        "uv sync --group build && "
        ".venv/bin/python scripts/build_core.py --platform linux-x64 --wheel"
    )
    _run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "-v",
            f"{repo}:/work",
            "-w",
            "/work",
            "python:3.13-bookworm",
            "bash",
            "-lc",
            script,
        ]
    )
    return _build_core_wheel(_require_venv_python(), _LINUX_X64)


def _build_release_wheel(python: Path) -> Path:
    _run([str(python), "scripts/build_release_wheel.py"])
    wheels = sorted((_REPO_ROOT / "dist").glob("myrm_agent_harness-*.whl"))
    if not wheels:
        msg = "No release wheel found in dist/"
        raise SystemExit(msg)
    return wheels[-1]


def _collect_wheels(upload_dir: Path) -> list[Path]:
    upload_dir.mkdir(parents=True, exist_ok=True)
    for existing in upload_dir.glob("*.whl"):
        existing.unlink()

    python = _require_venv_python()
    collected: list[Path] = []

    if _DARWIN_ARM64 not in PUBLISH_PLATFORMS:
        msg = f"rc1 local publish expects {_DARWIN_ARM64} in PUBLISH_PLATFORMS"
        raise SystemExit(msg)

    system = platform.system()
    machine = platform.machine().lower()
    if system != "Darwin" or machine not in {"arm64", "aarch64"}:
        msg = (
            "darwin-arm64 core wheel must be built on Apple Silicon macOS. "
            f"Current host: {system} {machine}"
        )
        raise SystemExit(msg)

    darwin_wheel = _build_core_wheel(python, _DARWIN_ARM64)
    collected.append(darwin_wheel)

    if _LINUX_X64 in PUBLISH_PLATFORMS:
        if system == "Linux" and machine in {"x86_64", "amd64"}:
            linux_wheel = _build_core_wheel(python, _LINUX_X64)
        else:
            linux_wheel = _build_linux_x64_in_docker()
        collected.append(linux_wheel)

    release_wheel = _build_release_wheel(python)
    collected.append(release_wheel)

    staged: list[Path] = []
    for wheel in collected:
        dest = upload_dir / wheel.name
        shutil.copy2(wheel, dest)
        staged.append(dest)
    return staged


def _upload(upload_dir: Path) -> None:
    _run([str(_require_venv_python()), "-m", "twine", "upload", "--skip-existing", f"{upload_dir}/*.whl"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Local rc1 PyPI publish (darwin-arm64 + linux-x64)")
    parser.add_argument(
        "--upload-dir",
        type=Path,
        default=_REPO_ROOT / "pypi-upload",
        help="Directory to stage wheels (default: pypi-upload/)",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload staged wheels to PyPI via twine after validation",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Poll PyPI after upload (implies --upload)",
    )
    args = parser.parse_args()

    version = read_harness_version(_REPO_ROOT)
    staged = _collect_wheels(args.upload_dir)
    validate_upload_dir(args.upload_dir, version)
    print("Staged wheels:")
    for wheel in staged:
        print(f"  {wheel.name}")

    if args.upload or args.verify:
        _upload(args.upload_dir)
    if args.verify:
        verify_published(version, max_attempts=12, delay_seconds=10.0)
    elif not args.upload:
        print(
            "Build complete. To upload: "
            f"TWINE_PASSWORD=<token> uv run python scripts/publish_pypi_rc1.py "
            f"--upload-dir {args.upload_dir} --upload --verify"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
