"""Tests for runtime lazy dependency installer."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from myrm_agent_harness.runtime import lazy_deps


@pytest.mark.parametrize(
    "feature,specs",
    [
        ("platform.discord", ("discord-py[voice]>=2.7.1",)),
        ("platform.feishu", ("lark-oapi>=1.6.8",)),
        ("platform.matrix", ("mautrix>=0.21.0", "aiohttp-socks>=0.11.0")),
        ("platform.matrix-e2ee", ("mautrix[encryption]>=0.21.0",)),
        ("platform.wechat-silk", ("pilk>=0.2.4",)),
    ],
)
def test_feature_specs_known(feature: str, specs: tuple[str, ...]) -> None:
    assert lazy_deps.feature_specs(feature) == specs


def test_feature_specs_unknown_raises() -> None:
    with pytest.raises(KeyError, match="Unknown lazy feature"):
        lazy_deps.feature_specs("platform.voice-tts")


def test_feature_missing_when_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "_is_satisfied", lambda _spec: True)
    assert lazy_deps.feature_missing("platform.matrix") == ()


def test_feature_missing_lists_unsatisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lazy_deps,
        "_is_satisfied",
        lambda spec: spec != "mautrix>=0.21.0",
    )
    assert lazy_deps.feature_missing("platform.matrix") == ("mautrix>=0.21.0",)


def test_ensure_raises_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "_is_satisfied", lambda _spec: False)
    monkeypatch.setattr(lazy_deps, "_allow_lazy_installs", lambda: False)
    with pytest.raises(lazy_deps.FeatureUnavailable, match="MYRM_DISABLE_LAZY_INSTALLS"):
        lazy_deps.ensure("platform.matrix", prompt=False)


def test_ensure_skips_install_when_already_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "_is_satisfied", lambda _spec: True)

    with patch.object(lazy_deps, "_venv_pip_install") as mock_install:
        lazy_deps.ensure("platform.matrix", prompt=False)

    mock_install.assert_not_called()


def test_ensure_unknown_feature_raises() -> None:
    with pytest.raises(lazy_deps.FeatureUnavailable, match="not in LAZY_DEPS allowlist"):
        lazy_deps.ensure("platform.unknown", prompt=False)


def test_ensure_rejects_unsafe_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "_is_satisfied", lambda _spec: False)
    monkeypatch.setattr(lazy_deps, "LAZY_DEPS", {"platform.test": ("bad;rm",)})

    with pytest.raises(lazy_deps.FeatureUnavailable, match="unsafe spec"):
        lazy_deps.ensure("platform.test", prompt=False)


def test_ensure_install_success(monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter([False, True])

    def _satisfied(_spec: str) -> bool:
        return next(states, True)

    monkeypatch.setattr(lazy_deps, "_is_satisfied", _satisfied)
    monkeypatch.setattr(
        lazy_deps,
        "_venv_pip_install",
        lambda _specs: lazy_deps._InstallResult(True, "ok", ""),
    )

    lazy_deps.ensure("platform.matrix", prompt=False)


def test_ensure_install_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "_is_satisfied", lambda _spec: False)
    monkeypatch.setattr(
        lazy_deps,
        "_venv_pip_install",
        lambda _specs: lazy_deps._InstallResult(False, "", "pip exploded"),
    )

    with pytest.raises(lazy_deps.FeatureUnavailable, match="install failed"):
        lazy_deps.ensure("platform.matrix", prompt=False)


def test_ensure_still_missing_after_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "_is_satisfied", lambda _spec: False)
    monkeypatch.setattr(
        lazy_deps,
        "_venv_pip_install",
        lambda _specs: lazy_deps._InstallResult(True, "ok", ""),
    )

    with pytest.raises(lazy_deps.FeatureUnavailable, match="still missing"):
        lazy_deps.ensure("platform.matrix", prompt=False)


@pytest.mark.parametrize(
    "env_value,expected",
    [
        ("1", False),
        ("true", False),
        ("yes", False),
        ("", True),
        ("0", True),
    ],
)
def test_allow_lazy_installs_env(monkeypatch: pytest.MonkeyPatch, env_value: str, expected: bool) -> None:
    monkeypatch.setenv("MYRM_DISABLE_LAZY_INSTALLS", env_value)
    assert lazy_deps._allow_lazy_installs() is expected


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("mautrix>=0.21.0", True),
        ("", False),
        ("bad;rm", False),
        ("-evil", False),
        ("pkg@git", False),
        ("a" * 201, False),
    ],
)
def test_spec_is_safe(spec: str, expected: bool) -> None:
    assert lazy_deps._spec_is_safe(spec) is expected


def test_pkg_name_and_specifier_helpers() -> None:
    assert lazy_deps._pkg_name_from_spec("mautrix[encryption]>=0.21.0") == "mautrix"
    assert lazy_deps._specifier_from_spec("mautrix[encryption]>=0.21.0") == ">=0.21.0"
    assert lazy_deps._specifier_from_spec("!!!") == ""


def test_is_satisfied_without_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _import(name: str, *args: object, **kwargs: object):
        if name == "importlib.metadata":
            raise ImportError("no metadata")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    assert lazy_deps._is_satisfied("mautrix>=0.21.0") is False


def test_is_satisfied_installed_no_specifier(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_metadata = SimpleNamespace(
        version=lambda _pkg: "1.0.0",
        PackageNotFoundError=type("PackageNotFoundError", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "importlib.metadata", fake_metadata)
    assert lazy_deps._is_satisfied("mautrix") is True


def test_is_satisfied_with_packaging_match(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_metadata = SimpleNamespace(
        version=lambda _pkg: "0.1.0",
        PackageNotFoundError=type("PackageNotFoundError", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "importlib.metadata", fake_metadata)
    assert lazy_deps._is_satisfied("mautrix>=0.21.0") is False


def test_venv_pip_install_empty_specs() -> None:
    result = lazy_deps._venv_pip_install(())
    assert result.success is True


def test_venv_pip_install_via_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps.shutil, "which", lambda _name: "/usr/bin/uv")
    proc = SimpleNamespace(returncode=0, stdout="installed", stderr="")
    monkeypatch.setattr(lazy_deps.subprocess, "run", lambda *args, **kwargs: proc)

    result = lazy_deps._venv_pip_install(("mautrix>=0.21.0",))
    assert result.success is True
    assert result.stdout == "installed"


def test_venv_pip_install_fallback_pip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps.shutil, "which", lambda _name: None)

    def _run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        if cmd[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="pip 24", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(lazy_deps.subprocess, "run", _run)
    result = lazy_deps._venv_pip_install(("mautrix>=0.21.0",))
    assert result.success is True


def test_venv_pip_install_pip_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps.shutil, "which", lambda _name: None)

    def _run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        if cmd[-1] == "--version":
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        raise subprocess.CalledProcessError(1, "ensurepip")

    monkeypatch.setattr(lazy_deps.subprocess, "run", _run)
    result = lazy_deps._venv_pip_install(("mautrix>=0.21.0",))
    assert result.success is False


def test_is_satisfied_package_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    class PackageNotFoundError(Exception):
        pass

    def _version(_pkg: str) -> str:
        raise PackageNotFoundError("missing")

    fake_metadata = SimpleNamespace(version=_version, PackageNotFoundError=PackageNotFoundError)
    monkeypatch.setitem(sys.modules, "importlib.metadata", fake_metadata)
    assert lazy_deps._is_satisfied("mautrix>=0.21.0") is False


def test_is_satisfied_without_packaging(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_metadata = SimpleNamespace(
        version=lambda _pkg: "0.1.0",
        PackageNotFoundError=type("PackageNotFoundError", (Exception,), {}),
    )
    monkeypatch.setitem(sys.modules, "importlib.metadata", fake_metadata)
    monkeypatch.setitem(sys.modules, "packaging.specifiers", None)
    monkeypatch.delitem(sys.modules, "packaging.version", raising=False)
    with patch.dict(sys.modules, {"packaging.specifiers": None}):
        import builtins

        real_import = builtins.__import__

        def _import(name: str, *args: object, **kwargs: object):
            if name == "packaging.specifiers" or name == "packaging.version":
                raise ImportError("no packaging")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _import)
        assert lazy_deps._is_satisfied("mautrix>=0.21.0") is True


def test_venv_pip_install_uv_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps.shutil, "which", lambda _name: "/usr/bin/uv")

    def _run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        if cmd[0].endswith("uv"):
            return SimpleNamespace(returncode=1, stdout="", stderr="uv failed")
        if cmd[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="pip 24", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(lazy_deps.subprocess, "run", _run)
    result = lazy_deps._venv_pip_install(("mautrix>=0.21.0",))
    assert result.success is True


def test_venv_pip_install_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps.shutil, "which", lambda _name: None)

    def _run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        if cmd[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="pip 24", stderr="")
        raise subprocess.TimeoutExpired(cmd="pip install", timeout=300)

    monkeypatch.setattr(lazy_deps.subprocess, "run", _run)
    result = lazy_deps._venv_pip_install(("mautrix>=0.21.0",))
    assert result.success is False


def test_clear_metadata_cache_no_cache_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "importlib.metadata", SimpleNamespace())
    lazy_deps._clear_metadata_cache()


def test_clear_metadata_cache_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_metadata = SimpleNamespace(_cache_clear=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setitem(sys.modules, "importlib.metadata", fake_metadata)
    lazy_deps._clear_metadata_cache()


def test_is_available_unknown_feature() -> None:
    assert lazy_deps.is_available("platform.voice-tts") is False


def test_is_available_when_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "feature_missing", lambda _feature: ())
    assert lazy_deps.is_available("platform.matrix") is True


def test_ensure_and_bind_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "ensure", lambda *_args, **_kwargs: None)

    target: dict[str, object] = {}
    ok = lazy_deps.ensure_and_bind(
        "platform.matrix",
        lambda: {"MatrixClient": object},
        target,
    )
    assert ok is True
    assert "MatrixClient" in target


def test_ensure_and_bind_returns_false_on_feature_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise lazy_deps.FeatureUnavailable("platform.matrix", ("mautrix>=0.21.0",), "nope")

    monkeypatch.setattr(lazy_deps, "ensure", _raise)
    assert lazy_deps.ensure_and_bind("platform.matrix", lambda: {}, {}) is False


def test_ensure_and_bind_returns_false_on_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "ensure", lambda *_args, **_kwargs: None)

    def _importer() -> dict[str, object]:
        raise ImportError("missing module")

    assert lazy_deps.ensure_and_bind("platform.matrix", _importer, {}) is False


def test_feature_unavailable_attributes() -> None:
    exc = lazy_deps.FeatureUnavailable("platform.matrix", ("mautrix>=0.21.0",), "test reason")
    assert exc.feature == "platform.matrix"
    assert exc.missing == ("mautrix>=0.21.0",)
    assert exc.reason == "test reason"
    assert "Manual install" in str(exc)
