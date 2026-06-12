"""Architecture gate: release wheel must ship browser static assets.

ad_domains.py loads domains via importlib.resources from assets/ad_domains.txt.
If the txt file is missing from the wheel, block_ad_domains fails at runtime on
pip-installed harness (cloud sandbox / PyPI consumers).
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[2]
_WHEEL_ASSET_SUFFIX = "myrm_agent_harness/toolkits/browser/assets/ad_domains.txt"
_MIN_DOMAIN_LINES = 3500


@pytest.mark.architecture
def test_release_wheel_includes_browser_ad_domains_asset(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    result = subprocess.run(
        ["uv", "build", "--wheel", "-o", str(dist_dir)],
        cwd=HARNESS_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    wheels = sorted(dist_dir.glob("myrm_agent_harness-*.whl"))
    assert wheels, "expected uv build to produce a wheel"

    with zipfile.ZipFile(wheels[-1]) as archive:
        matches = [name for name in archive.namelist() if name.endswith(_WHEEL_ASSET_SUFFIX)]
        assert len(matches) == 1, f"missing {_WHEEL_ASSET_SUFFIX} in wheel"

        body = archive.read(matches[0]).decode("utf-8")
        domain_lines = sum(
            1 for line in body.splitlines() if line.strip() and not line.startswith("#")
        )
        assert domain_lines >= _MIN_DOMAIN_LINES, domain_lines
