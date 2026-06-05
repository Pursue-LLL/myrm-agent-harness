"""Python toolchain probe for bash tool description injection.

Detects Python environment state (version, pip availability, PEP-668 status,
uv presence) at process startup and produces a single deterministic line.
This line is appended to the bash tool description so the LLM avoids blind
trial-and-error when installing packages.

Design principles:
- Zero token cost when environment is healthy (returns empty string).
- Process-level cache (deterministic for agent lifetime).
- Never crashes — failures silently return empty string.
- Does NOT skip container environments (unlike Hermes): our agent runs
  inside the sandbox, so the probe is always relevant.

[INPUT]
- (none — reads host environment via subprocess)

[OUTPUT]
- get_environment_probe_line: Cached one-liner or "" if environment is clean.

[POS]
Python toolchain probe. Injects environment awareness into bash tool
description to eliminate pip install retry loops.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_CACHED_LINE: str | None = None


def _run(cmd: list[str], timeout: float = 3.0) -> tuple[int, str, str]:
    """Run a short subprocess. Returns (returncode, stdout, stderr).

    Failures (binary missing, timeout, OSError) return (-1, "", "<reason>").
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
    except FileNotFoundError:
        return -1, "", "not found"
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except OSError as exc:
        return -1, "", f"oserror: {exc}"


def _python_version_of(binary: str) -> str | None:
    """Return version string like '3.12.4' for the given binary, or None."""
    if not shutil.which(binary):
        return None
    rc, out, _err = _run(
        [
            binary,
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
        ]
    )
    if rc == 0 and out:
        return out
    return None


def _has_pip_module(binary: str) -> bool:
    """True if `<binary> -m pip --version` succeeds."""
    if not shutil.which(binary):
        return False
    rc, _out, _err = _run([binary, "-m", "pip", "--version"])
    return rc == 0


def _detect_pep668(binary: str) -> bool:
    """True when the binary's install location is PEP-668 externally-managed."""
    if not shutil.which(binary):
        return False
    code = (
        "import sys, os;"
        "stdlib = os.path.dirname(os.__file__);"
        "marker = os.path.join(stdlib, 'EXTERNALLY-MANAGED');"
        "print('yes' if os.path.exists(marker) else 'no')"
    )
    rc, out, _err = _run([binary, "-c", code])
    return rc == 0 and out.strip() == "yes"


def _pip_python_version() -> str | None:
    """If `pip` is on PATH, return the Python version it's bound to.

    Parses the trailing `(python X.Y)` from `pip --version` output.
    """
    if not shutil.which("pip"):
        return None
    rc, out, _err = _run(["pip", "--version"])
    if rc != 0 or not out:
        return None
    if "(python " in out and out.endswith(")"):
        try:
            tail = out.rsplit("(python ", 1)[1]
            return tail[:-1].strip()
        except (IndexError, AttributeError):
            return None
    return None


def _build_probe_line() -> str:
    """Build the one-liner. Returns "" when nothing notable is detected."""
    py3_ver = _python_version_of("python3")
    py_ver = _python_version_of("python")
    py3_has_pip = _has_pip_module("python3") if py3_ver else False
    pip_bound_to = _pip_python_version()
    py3_pep668 = _detect_pep668("python3") if py3_ver else False
    has_uv = shutil.which("uv") is not None

    mismatch = bool(pip_bound_to and py3_ver and not py3_ver.startswith(pip_bound_to))

    silent_conditions = py3_ver is not None and py3_has_pip and not mismatch and (not py3_pep668 or has_uv)
    if silent_conditions:
        return ""

    bits: list[str] = []
    if py3_ver:
        py3_bit = f"python3={py3_ver}"
        if not py3_has_pip:
            py3_bit += " (no pip module)"
        bits.append(py3_bit)
    else:
        bits.append("python3=missing")

    if py_ver and py_ver != py3_ver:
        bits.append(f"python={py_ver}")
    elif not py_ver and py3_ver:
        bits.append("python=missing (use python3)")

    if pip_bound_to:
        if mismatch:
            bits.append(f"pip→python{pip_bound_to} (mismatch)")
        elif not py3_has_pip:
            bits.append(f"pip→python{pip_bound_to}")
    elif not py3_has_pip:
        bits.append("pip=missing")

    if py3_pep668:
        bits.append("PEP 668=yes (use venv or uv)")

    if has_uv:
        bits.append("uv=installed")

    if not bits:
        return ""

    return "Python toolchain: " + ", ".join(bits) + "."


def get_environment_probe_line(*, force_refresh: bool = False) -> str:
    """Return the cached probe line (building it on first call).

    Returns "" when the environment is clean — the caller should skip
    appending anything in that case.

    Args:
        force_refresh: For tests only; clears the cache before probing.
    """
    global _CACHED_LINE
    if force_refresh:
        with _CACHE_LOCK:
            _CACHED_LINE = None

    if _CACHED_LINE is not None:
        return _CACHED_LINE

    with _CACHE_LOCK:
        if _CACHED_LINE is not None:
            return _CACHED_LINE
        try:
            line = _build_probe_line()
        except Exception as exc:
            logger.debug("env_probe failed: %s", exc)
            line = ""
        _CACHED_LINE = line
        return line


def _reset_cache_for_tests() -> None:
    """Test helper — clear the cache between probe scenarios."""
    global _CACHED_LINE
    with _CACHE_LOCK:
        _CACHED_LINE = None
