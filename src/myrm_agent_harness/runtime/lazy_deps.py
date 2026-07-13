"""Lazy dependency installer for optional platform backends.

Installs allowlisted packages into the active venv on demand (uv pip, then pip).
Used by myrm-agent-server channel and voice management so GUI users need not run terminal
commands for optional extras such as Matrix (mautrix) or Edge TTS (edge-tts).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Keys are dot-separated feature names. Values match myrm-agent-server optional extras.
LAZY_DEPS: dict[str, tuple[str, ...]] = {
    "platform.discord": ("discord-py[voice]>=2.7.1",),
    "platform.feishu": ("lark-oapi>=1.6.8",),
    "platform.matrix": (
        "mautrix>=0.21.0",
        "aiohttp-socks>=0.11.0",
    ),
    "platform.matrix-e2ee": ("mautrix[encryption]>=0.21.0",),
    "platform.wechat-silk": ("pilk>=0.2.4",),
    "platform.voice-tts": ("edge-tts>=7.2.8",),
}

_SAFE_SPEC = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*"
    r"(?:\[[A-Za-z0-9_,\-]+\])?"
    r"(?:[<>=!~]=?[A-Za-z0-9_.\-+,*<>=!~]+)?$"
)


class FeatureUnavailable(RuntimeError):
    """Lazy feature cannot be installed or is disabled."""

    def __init__(self, feature: str, missing: tuple[str, ...], reason: str) -> None:
        self.feature = feature
        self.missing = missing
        self.reason = reason
        super().__init__(
            f"Feature {feature!r} unavailable: {reason}. "
            f"Manual install: uv pip install {' '.join(repr(s) for s in missing)}"
        )


@dataclass(frozen=True)
class _InstallResult:
    success: bool
    stdout: str
    stderr: str


def _allow_lazy_installs() -> bool:
    if os.environ.get("MYRM_DISABLE_LAZY_INSTALLS", "").strip() in {"1", "true", "yes"}:
        return False
    return True


def _spec_is_safe(spec: str) -> bool:
    if not spec or len(spec) > 200:
        return False
    if any(ch in spec for ch in (";", "|", "&", "`", "$", "\n", "\r", "\t", "\\")):
        return False
    if spec.startswith(("-", "/", ".")) or "://" in spec or "@" in spec:
        return False
    return bool(_SAFE_SPEC.match(spec))


def _pkg_name_from_spec(spec: str) -> str:
    match = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_.\-]*)", spec)
    return match.group(1) if match else spec


def _specifier_from_spec(spec: str) -> str:
    match = re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(?:\[[A-Za-z0-9_,\-]+\])?", spec)
    if not match:
        return ""
    return spec[match.end() :]


def _is_satisfied(spec: str) -> bool:
    pkg = _pkg_name_from_spec(spec)
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return False
    try:
        installed = version(pkg)
    except PackageNotFoundError:
        return False
    except Exception:
        return False

    spec_tail = _specifier_from_spec(spec)
    if not spec_tail:
        return True

    try:
        from packaging.specifiers import InvalidSpecifier, SpecifierSet
        from packaging.version import InvalidVersion, Version
    except ImportError:
        return True

    try:
        return Version(installed) in SpecifierSet(spec_tail)
    except (InvalidSpecifier, InvalidVersion, Exception):
        return True


def _venv_pip_install(specs: tuple[str, ...], *, timeout: int = 300) -> _InstallResult:
    if not specs:
        return _InstallResult(True, "", "")

    venv_root = Path(sys.executable).parent.parent
    uv_env = {**os.environ, "VIRTUAL_ENV": str(venv_root)}

    uv_bin = shutil.which("uv")
    if uv_bin:
        try:
            proc = subprocess.run(
                [uv_bin, "pip", "install", *specs],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=uv_env,
            )
            if proc.returncode == 0:
                return _InstallResult(True, proc.stdout or "", proc.stderr or "")
            logger.debug("uv pip install failed: %s", proc.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.debug("uv invocation failed: %s", exc)

    pip_cmd = [sys.executable, "-m", "pip"]
    try:
        probe = subprocess.run(pip_cmd + ["--version"], capture_output=True, text=True, timeout=15)
        if probe.returncode != 0:
            raise FileNotFoundError("pip not in venv")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        try:
            subprocess.run(
                [sys.executable, "-m", "ensurepip", "--upgrade", "--default-pip"],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            return _InstallResult(False, "", f"pip not available and ensurepip failed: {exc}")

    try:
        proc = subprocess.run(
            pip_cmd + ["install", *specs],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return _InstallResult(proc.returncode == 0, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        return _InstallResult(False, "", f"pip install timed out: {exc}")
    except Exception as exc:
        return _InstallResult(False, "", f"pip install failed: {exc}")


def _clear_metadata_cache() -> None:
    try:
        import importlib.metadata as metadata

        if hasattr(metadata, "_cache_clear"):
            metadata._cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass


def feature_specs(feature: str) -> tuple[str, ...]:
    if feature not in LAZY_DEPS:
        raise KeyError(f"Unknown lazy feature: {feature!r}")
    return LAZY_DEPS[feature]


def feature_missing(feature: str) -> tuple[str, ...]:
    return tuple(spec for spec in feature_specs(feature) if not _is_satisfied(spec))


def ensure(feature: str, *, prompt: bool = False) -> None:
    """Install allowlisted packages for ``feature`` into the active venv."""
    del prompt  # GUI/server callers always disable TTY prompts
    if feature not in LAZY_DEPS:
        raise FeatureUnavailable(feature, (), f"feature {feature!r} not in LAZY_DEPS allowlist")

    missing = feature_missing(feature)
    if not missing:
        return

    for spec in missing:
        if not _spec_is_safe(spec):
            raise FeatureUnavailable(feature, missing, f"refusing to install unsafe spec {spec!r}")

    if not _allow_lazy_installs():
        raise FeatureUnavailable(
            feature,
            missing,
            "lazy installs disabled (MYRM_DISABLE_LAZY_INSTALLS=1)",
        )

    logger.info("Lazy-installing %s for feature %r", " ".join(missing), feature)
    result = _venv_pip_install(missing)
    if not result.success:
        snippet = (result.stderr or result.stdout or "").strip()[-2000:]
        raise FeatureUnavailable(feature, missing, f"install failed: {snippet or 'no error output'}")

    _clear_metadata_cache()
    still_missing = feature_missing(feature)
    if still_missing:
        raise FeatureUnavailable(
            feature,
            still_missing,
            "install reported success but packages still missing (may require process restart)",
        )
    logger.info("Lazy install complete for feature %r", feature)


def is_available(feature: str) -> bool:
    if feature not in LAZY_DEPS:
        return False
    return not feature_missing(feature)


def ensure_and_bind(
    feature: str,
    importer: Callable[[], dict[str, Any]],
    target_globals: dict[str, Any],
) -> bool:
    """Ensure feature deps, then merge ``importer()`` into ``target_globals``."""
    try:
        ensure(feature, prompt=False)
    except (FeatureUnavailable, Exception):
        return False
    try:
        bindings = importer()
    except ImportError:
        return False
    target_globals.update(bindings)
    return True
