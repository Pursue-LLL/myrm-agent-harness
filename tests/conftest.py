from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

# Python 3.13 / Pydantic 2.13.x / LiteLLM generic creation workaround
try:
    import sys

    import pydantic.root_model
    sys.modules["pydantic.root_model"] = pydantic.root_model
except ImportError:
    pass

import pytest
from blockbuster import BlockBuster

logger = logging.getLogger(__name__)

# Run at import time to isolate harness tests as well
_temp_workspace = tempfile.mkdtemp(prefix="myrm_harness_test_")
os.environ["MYRM_DATA_DIR"] = _temp_workspace


def _cleanup_temp_workspace() -> None:
    with suppress(Exception):
        shutil.rmtree(_temp_workspace, ignore_errors=True)


atexit.register(_cleanup_temp_workspace)


# i18n locale files live in the server project; load them at import time
# so every xdist worker has translations available for diagnostics tests.
_SERVER_LOCALES_DIR = (
    Path(__file__).parent.parent.parent
    / "myrm-agent-server"
    / "app"
    / "channels"
    / "i18n"
    / "locales"
)


def _load_server_locales_once() -> None:
    if not _SERVER_LOCALES_DIR.is_dir():
        return
    try:
        from myrm_agent_harness.agent.errors.diagnostics.i18n import (
            get_locale_manager,
        )
    except Exception:
        return

    manager = get_locale_manager()
    if manager.get_supported_locales():
        return

    for name in ["en", "zh-CN", "ja", "ko", "de"]:
        json_path = _SERVER_LOCALES_DIR / f"{name}.json"
        if not json_path.exists():
            continue
        try:
            with open(json_path, encoding="utf-8") as f:
                flat_data = json.load(f)

            trans: dict[str, dict[str, str | list[str]]] = {}
            for k, v in flat_data.items():
                if k.startswith("cooldown_hint_"):
                    trans.setdefault("_cooldown_hint", {})[
                        k.replace("cooldown_hint_", "")
                    ] = v
                    continue
                if k.endswith("_resolution_steps"):
                    trans.setdefault(k.replace("_resolution_steps", ""), {})[
                        "resolution_steps"
                    ] = v
                elif k.endswith("_user_message"):
                    trans.setdefault(k.replace("_user_message", ""), {})[
                        "user_message"
                    ] = v

            manager.register_translations(name, trans)
            if name == "zh-CN":
                manager.register_translations("zh_cn", trans)
        except Exception as e:
            logger.warning("Failed to load test locale %s: %s", json_path, e)


_load_server_locales_once()


# ---------------------------------------------------------------------------
# Blocking-IO runtime detection (blockbuster)
#
# Follows deer-flow's pattern: blockbuster is opt-in via the
# ``tests/blocking_io/`` directory. Tests in that directory run under
# a strict blockbuster gate; all other tests are unaffected.
#
# Individual tests elsewhere can also opt-in by using the
# ``blocking_io_gate`` fixture directly.
# ---------------------------------------------------------------------------

_SCANNED_MODULES: tuple[str, ...] = ("myrm_agent_harness",)

_BLOCKING_IO_TEST_ROOT = Path(__file__).resolve().parent / "blocking_io"


@contextmanager
def _blocking_io_gate_ctx() -> Iterator[BlockBuster]:
    """Activate blockbuster scoped to harness business code only."""
    bb = BlockBuster(scanned_modules=list(_SCANNED_MODULES))
    try:
        bb.activate()
        yield bb
    finally:
        bb.deactivate()


@pytest.fixture
def blocking_io_gate() -> Iterator[BlockBuster]:
    """Fixture that activates blockbuster for a single test."""
    with _blocking_io_gate_ctx() as bb:
        yield bb


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    """Auto-gate tests under tests/blocking_io/ with blockbuster.

    Uses ``pytest_runtest_call`` (not ``pytest_runtest_protocol``) so
    session-scoped fixtures run outside the blockbuster gate.
    """
    item_path = Path(item.path).resolve()
    if not item_path.is_relative_to(_BLOCKING_IO_TEST_ROOT):
        yield
        return

    if item.get_closest_marker("allow_blocking_io") is not None:
        yield
        return

    with _blocking_io_gate_ctx():
        yield
