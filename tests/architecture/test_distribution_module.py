"""Unit tests for myrm_agent_harness.runtime.install_guard (probe, platform, verify)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from importlib.metadata import PackageNotFoundError
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.runtime.install_guard.probe import (
    DistributionMode,
    DistributionNotReadyError,
    assert_distribution_ready,
    get_distribution_mode,
    is_compiled_distribution,
)
from myrm_agent_harness.runtime.install_guard.platform import get_runtime_platform_key
from myrm_agent_harness.runtime.install_guard.verify import (
    run_verification,
    verify_core_runtime_imports,
    verify_distribution_ready,
    verify_manifest_imports,
    verify_public_api,
)


@pytest.fixture(autouse=True)
def _clear_distribution_mode_cache() -> None:
    get_distribution_mode.cache_clear()


@pytest.mark.architecture
def test_get_distribution_mode_source_in_editable_install() -> None:
    mode = get_distribution_mode()
    assert mode is DistributionMode.SOURCE
    assert is_compiled_distribution() is False


@pytest.mark.architecture
def test_assert_distribution_ready_passes_in_source_mode() -> None:
    assert_distribution_ready()


@pytest.mark.architecture
def test_get_runtime_platform_key_matches_known_platforms() -> None:
    key = get_runtime_platform_key()
    assert key
    if sys.platform == "darwin":
        assert key.startswith("darwin-")
    elif sys.platform == "linux":
        assert key.startswith("linux-")
    elif sys.platform == "win32":
        assert key.startswith("win32-")


@pytest.mark.architecture
def test_verify_manifest_and_public_api_in_source_mode() -> None:
    verify_manifest_imports()
    verify_distribution_ready()
    verify_core_runtime_imports()
    verify_public_api()


@pytest.mark.architecture
def test_run_verification_source_mode(capsys: pytest.CaptureFixture[str]) -> None:
    run_verification(matplotlib_cjk=False)
    assert "harness distribution OK" in capsys.readouterr().out


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.verify.verify_matplotlib_cjk")
def test_run_verification_optional_matplotlib_cjk(
    cjk_mock: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_verification(matplotlib_cjk=True)
    cjk_mock.assert_called_once()
    assert "harness distribution OK" in capsys.readouterr().out


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.probe.find_spec", return_value=None)
@patch("myrm_agent_harness.runtime.install_guard.probe._manifest_py_present", return_value=False)
def test_get_distribution_mode_incomplete_without_core(
    _manifest: MagicMock,
    _find_spec: MagicMock,
) -> None:
    assert get_distribution_mode() is DistributionMode.INCOMPLETE


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.probe._import_core_ip_module")
@patch("myrm_agent_harness.runtime.install_guard.probe.find_spec")
@patch("myrm_agent_harness.runtime.install_guard.probe._manifest_py_present", return_value=False)
def test_get_distribution_mode_compiled_when_core_imports_succeed(
    _manifest: MagicMock,
    find_spec_mock: MagicMock,
    import_mock: MagicMock,
) -> None:
    find_spec_mock.return_value = MagicMock()
    assert get_distribution_mode() is DistributionMode.COMPILED
    assert is_compiled_distribution() is True
    import_mock.assert_called()


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.probe._import_core_ip_module", side_effect=ImportError("x"))
@patch("myrm_agent_harness.runtime.install_guard.probe.find_spec")
@patch("myrm_agent_harness.runtime.install_guard.probe._manifest_py_present", return_value=False)
def test_assert_distribution_ready_raises_when_modules_missing(
    _manifest: MagicMock,
    find_spec_mock: MagicMock,
    _import_mock: MagicMock,
) -> None:
    find_spec_mock.return_value = MagicMock()
    with pytest.raises(DistributionNotReadyError, match="Harness distribution incomplete"):
        assert_distribution_ready()


@pytest.mark.architecture
@patch(
    "myrm_agent_harness.runtime.install_guard.platform.get_runtime_platform_key",
    return_value="darwin-arm64",
)
@patch("myrm_agent_harness.runtime.install_guard.probe.pkg_version", return_value="1.0.0")
@patch("myrm_agent_harness.runtime.install_guard.probe._import_core_ip_module")
@patch("myrm_agent_harness.runtime.install_guard.probe.find_spec")
@patch("myrm_agent_harness.runtime.install_guard.probe._manifest_py_present", return_value=False)
def test_assert_distribution_ready_raises_on_platform_key_mismatch(
    _manifest: MagicMock,
    find_spec_mock: MagicMock,
    _import_mock: MagicMock,
    _pkg_version: MagicMock,
    _runtime_key: MagicMock,
) -> None:
    find_spec_mock.return_value = MagicMock()
    core_mod = ModuleType("myrm_agent_harness_core")
    core_mod.__version__ = "1.0.0"
    core_mod.get_platform_key = lambda: "linux-x64"
    with (
        patch.dict(sys.modules, {"myrm_agent_harness_core": core_mod}),
        pytest.raises(DistributionNotReadyError, match="platform core wheel mismatch"),
    ):
        assert_distribution_ready()


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.probe.pkg_version", return_value="2.0.0")
@patch("myrm_agent_harness.runtime.install_guard.probe._import_core_ip_module")
@patch("myrm_agent_harness.runtime.install_guard.probe.find_spec")
@patch("myrm_agent_harness.runtime.install_guard.probe._manifest_py_present", return_value=False)
def test_assert_distribution_ready_raises_on_version_mismatch(
    _manifest: MagicMock,
    find_spec_mock: MagicMock,
    _import_mock: MagicMock,
    _pkg_version: MagicMock,
) -> None:
    find_spec_mock.return_value = MagicMock()
    core_mod = ModuleType("myrm_agent_harness_core")
    core_mod.__version__ = "1.0.0"
    core_mod.get_platform_key = lambda: "unknown"
    with (
        patch.dict(sys.modules, {"myrm_agent_harness_core": core_mod}),
        pytest.raises(DistributionNotReadyError, match="version mismatch"),
    ):
        assert_distribution_ready()


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.platform.platform.machine", return_value="x86_64")
@patch("myrm_agent_harness.runtime.install_guard.platform.sys.platform", "linux")
def test_runtime_platform_key_linux_glibc(_machine: MagicMock) -> None:
    assert get_runtime_platform_key() == "linux-x64"


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.platform.platform.machine", return_value="arm64")
@patch("myrm_agent_harness.runtime.install_guard.platform.sys.platform", "win32")
def test_runtime_platform_key_win32(_machine: MagicMock) -> None:
    assert get_runtime_platform_key() == "win32-arm64"


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.platform.sys.platform", "linux")
@patch("myrm_agent_harness.runtime.install_guard.platform.platform.machine", return_value="aarch64")
@patch("myrm_agent_harness.runtime.install_guard.platform._is_musl_linux", return_value=True)
def test_runtime_platform_key_linux_musl(
    _musl: MagicMock,
    _machine: MagicMock,
) -> None:
    assert get_runtime_platform_key() == "linux-arm64-musl"


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.platform.sys.platform", "freebsd")
@patch("myrm_agent_harness.runtime.install_guard.platform.platform.machine", return_value="riscv64")
def test_runtime_platform_key_unsupported_raises(
    _machine: MagicMock,
) -> None:
    with pytest.raises(RuntimeError, match="Unsupported platform"):
        get_runtime_platform_key()


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.verify.verify_public_api", side_effect=RuntimeError("boom"))
def test_run_verification_propagates_failures(_api: MagicMock) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        run_verification()


@pytest.mark.architecture
@patch("sys.argv", ["verify-harness-distribution"])
def test_verify_main_success(capsys: pytest.CaptureFixture[str]) -> None:
    from myrm_agent_harness.runtime.install_guard.verify import main

    main()
    assert "harness distribution OK" in capsys.readouterr().out


@pytest.mark.architecture
@patch("sys.argv", ["verify-harness-distribution"])
@patch("myrm_agent_harness.runtime.install_guard.verify.run_verification", side_effect=ValueError("bad install"))
def test_verify_main_failure_exit_one(_run: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    from myrm_agent_harness.runtime.install_guard.verify import main

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "verification FAILED" in capsys.readouterr().err


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.probe.importlib.import_module")
def test_import_core_ip_module_imports_target(import_mock: MagicMock) -> None:
    from myrm_agent_harness.runtime.install_guard.probe import _import_core_ip_module

    name = "myrm_agent_harness.agent.context_management.pipeline.engine"
    _import_core_ip_module(name)
    import_mock.assert_any_call(name)


@pytest.mark.architecture
@patch("myrm_agent_harness.api.create_skill_agent", new=123)
def test_verify_public_api_rejects_non_callable() -> None:
    with pytest.raises(TypeError, match="not callable"):
        verify_public_api()


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.verify.verify_matplotlib_cjk")
def test_run_verification_optional_matplotlib_cjk(matplotlib_mock: MagicMock) -> None:
    run_verification(matplotlib_cjk=True)
    matplotlib_mock.assert_called_once()


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.probe._import_core_ip_module", side_effect=KeyError("parent"))
@patch("myrm_agent_harness.runtime.install_guard.probe.find_spec")
@patch("myrm_agent_harness.runtime.install_guard.probe._manifest_py_present", return_value=False)
def test_get_distribution_mode_incomplete_on_import_key_error(
    _manifest: MagicMock,
    find_spec_mock: MagicMock,
    _import_mock: MagicMock,
) -> None:
    find_spec_mock.return_value = MagicMock()
    assert get_distribution_mode() is DistributionMode.INCOMPLETE


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.probe.pkg_version", side_effect=PackageNotFoundError("x"))
@patch("myrm_agent_harness.runtime.install_guard.probe._import_core_ip_module")
@patch("myrm_agent_harness.runtime.install_guard.probe.find_spec")
@patch("myrm_agent_harness.runtime.install_guard.probe._manifest_py_present", return_value=False)
def test_assert_distribution_ready_raises_on_unknown_platform_key_without_pkg_metadata(
    _manifest: MagicMock,
    find_spec_mock: MagicMock,
    _import_mock: MagicMock,
    _pkg_version: MagicMock,
) -> None:
    find_spec_mock.return_value = MagicMock()
    core_mod = ModuleType("myrm_agent_harness_core")
    core_mod.__version__ = "1.0.0"
    core_mod.get_platform_key = lambda: "unknown"
    with (
        patch.dict(sys.modules, {"myrm_agent_harness_core": core_mod}),
        pytest.raises(DistributionNotReadyError, match="not stamped with a platform key"),
    ):
        assert_distribution_ready()


@pytest.mark.architecture
@patch(
    "myrm_agent_harness.runtime.install_guard.platform.get_runtime_platform_key",
    return_value="linux-x64",
)
@patch("myrm_agent_harness.runtime.install_guard.probe.pkg_version", side_effect=PackageNotFoundError("x"))
@patch("myrm_agent_harness.runtime.install_guard.probe._import_core_ip_module")
@patch("myrm_agent_harness.runtime.install_guard.probe.find_spec")
@patch("myrm_agent_harness.runtime.install_guard.probe._manifest_py_present", return_value=False)
def test_assert_distribution_ready_skips_version_check_without_pkg(
    _manifest: MagicMock,
    find_spec_mock: MagicMock,
    _import_mock: MagicMock,
    _pkg_version: MagicMock,
    _runtime_key: MagicMock,
) -> None:
    find_spec_mock.return_value = MagicMock()
    core_mod = ModuleType("myrm_agent_harness_core")
    core_mod.__version__ = "1.0.0"
    core_mod.get_platform_key = lambda: "linux-x64"
    with patch.dict(sys.modules, {"myrm_agent_harness_core": core_mod}):
        assert_distribution_ready()


@pytest.mark.architecture
@patch("myrm_agent_harness.runtime.install_guard.platform.sys.platform", "linux")
def test_is_musl_linux_false_on_non_linux() -> None:
    from myrm_agent_harness.runtime.install_guard.platform import _is_musl_linux

    assert _is_musl_linux() is False


@pytest.mark.architecture
def test_is_musl_linux_detects_missing_glibc_header() -> None:
    from myrm_agent_harness.runtime.install_guard import platform as rp

    mock_sys = MagicMock()
    mock_sys.platform = "linux"
    mock_sys.report.getReport.return_value = {"header": {}}
    with patch.object(rp, "sys", mock_sys):
        assert rp._is_musl_linux() is True


@pytest.mark.architecture
def test_is_musl_linux_false_when_glibc_present() -> None:
    from myrm_agent_harness.runtime.install_guard import platform as rp

    mock_sys = MagicMock()
    mock_sys.platform = "linux"
    mock_sys.report.getReport.return_value = {"header": {"glibcVersionRuntime": "2.35"}}
    with patch.object(rp, "sys", mock_sys):
        assert rp._is_musl_linux() is False


@pytest.mark.architecture
def test_verify_matplotlib_cjk_without_matplotlib_installed(tmp_path: Path) -> None:
    """Cover CJK verify body when matplotlib is not a real venv dependency."""
    font_file = tmp_path / "NotoSansCJK-Regular.ttc"
    font_file.write_bytes(b"font")

    mock_plt = MagicMock()
    mock_fig = MagicMock()
    mock_ax = MagicMock()
    mock_plt.subplots.return_value = (mock_fig, mock_ax)

    mock_font_manager = MagicMock()
    mock_font_manager.fontManager.addfont = MagicMock()
    mock_font_manager.findfont.return_value = "/cache/NotoSansCJK-Regular.ttc"
    mock_font_manager.FontProperties.return_value = MagicMock()

    mock_matplotlib = MagicMock()
    mock_matplotlib.use = MagicMock()
    mock_matplotlib.font_manager = mock_font_manager
    mock_matplotlib.pyplot = mock_plt
    module_stubs = {
        "matplotlib": mock_matplotlib,
        "matplotlib.pyplot": mock_plt,
        "matplotlib.font_manager": mock_font_manager,
    }
    with patch.dict(sys.modules, module_stubs):
        with patch("pathlib.Path") as path_cls:
            path_cls.return_value.glob.return_value = iter([font_file])
            from myrm_agent_harness.runtime.install_guard.verify import verify_matplotlib_cjk

            verify_matplotlib_cjk()

    mock_matplotlib.use.assert_called_once_with("Agg")
    mock_fig.savefig.assert_called_once_with("/tmp/_mpl_verify.png")
