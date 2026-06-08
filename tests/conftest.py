from __future__ import annotations

import atexit
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
os.environ["OTEL_METRICS_EXPORTER"] = "none"
os.environ["OTEL_TRACES_EXPORTER"] = "none"


def _cleanup_temp_workspace() -> None:
    with suppress(Exception):
        shutil.rmtree(_temp_workspace, ignore_errors=True)


atexit.register(_cleanup_temp_workspace)


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
