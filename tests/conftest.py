from __future__ import annotations

import atexit
import inspect
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

# Python 3.13 / Pydantic 2.13.x / LiteLLM generic creation workaround
try:
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

_env_test_candidates = (
    Path(__file__).resolve().parent.parent.parent / "myrm-agent" / "myrm-agent-server" / ".env.test",
    Path(__file__).resolve().parent.parent / ".env.test",
)
for _candidate in _env_test_candidates:
    if _candidate.exists():
        with suppress(ImportError):
            from dotenv import load_dotenv

            load_dotenv(_candidate, override=False)
        break


def _cleanup_temp_workspace() -> None:
    with suppress(Exception):
        shutil.rmtree(_temp_workspace, ignore_errors=True)


atexit.register(_cleanup_temp_workspace)


def _cleanup_browser_child_processes() -> None:
    from tests.support.browser_process_cleanup import terminate_browser_processes_in_tree

    with suppress(Exception):
        terminate_browser_processes_in_tree(os.getpid())


atexit.register(_cleanup_browser_child_processes)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _cleanup_browser_child_processes()
    with suppress(Exception):
        from myrm_agent_harness.agent.sub_agents.checkpointer import reset_subagent_checkpointer

        reset_subagent_checkpointer()


def _reset_subagent_checkpointer_if_loaded() -> None:
    module = sys.modules.get("myrm_agent_harness.agent.sub_agents.checkpointer")
    if module is not None:
        module.reset_subagent_checkpointer()


@pytest.fixture(autouse=True)
def _isolate_subagent_checkpointer() -> Iterator[None]:
    """Give every test its own sub-agent checkpointer.

    The process-wide sqlite saver binds an ``asyncio.Lock`` and an aiosqlite worker thread to the event
    loop of the test that first used it. Each test runs on a fresh loop, so a survivor makes later tests
    fail with "bound to a different event loop" or an unhandled "Event loop is closed" thread error.
    """
    _reset_subagent_checkpointer_if_loaded()
    yield
    _reset_subagent_checkpointer_if_loaded()


_BROWSER_TEST_ROOT = Path(__file__).resolve().parent / "toolkits" / "browser"
_TESTS_ROOT = Path(__file__).resolve().parent
_INTEGRATION_TEST_ROOT = _TESTS_ROOT / "integration"


def _needs_browser_singleton_reset(request: pytest.FixtureRequest) -> bool:
    """Return whether a test may touch the GlobalBrowserPool singleton."""
    item_path = Path(request.fspath).resolve()
    return bool(item_path.is_relative_to(_BROWSER_TEST_ROOT))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Align markers with CI/local memory-safe test selection.

    ``@pytest.mark.benchmark`` tests spawn large corpora or heavy fixtures but were
    not excluded by ``-m "not performance"``. Treat them as performance tests.

    Real Chromium browser tests under ``tests/toolkits/browser`` are serialized
    when pytest-xdist is enabled to avoid N workers each launching a browser.
    """
    for item in items:
        if item.get_closest_marker("benchmark") is not None and item.get_closest_marker("performance") is None:
            item.add_marker(pytest.mark.performance)

        item_path = Path(item.path).resolve()
        in_browser_tree = item_path.is_relative_to(_BROWSER_TEST_ROOT)
        in_integration_tree = item_path.is_relative_to(_INTEGRATION_TEST_ROOT)
        if not in_browser_tree and not in_integration_tree:
            continue
        if item.get_closest_marker("xdist_group") is not None:
            continue
        if item.get_closest_marker("integration") is None and item.get_closest_marker("e2e") is None:
            continue
        item.add_marker(pytest.mark.xdist_group("browser_chromium"))


_BROWSER_HEAVY_TEST_MARKERS = ("integration", "e2e", "performance")
_BROWSER_REAL_CHROMIUM_CALLS = (".warmup(", ".acquire_page(")


def pytest_collection_finish(session: pytest.Session) -> None:
    """Fail fast when a browser test touches Chromium without heavy-test markers.

    Real ``warmup()`` / ``acquire_page()`` calls must not enter the default
    memory-safe suite (``-m "not integration and not e2e and not performance"``).
    """
    for item in session.items:
        item_path = Path(item.path).resolve()
        if not item_path.is_relative_to(_BROWSER_TEST_ROOT):
            continue
        if any(item.get_closest_marker(name) is not None for name in _BROWSER_HEAVY_TEST_MARKERS):
            continue
        try:
            source = inspect.getsource(item.function)
        except (OSError, TypeError):
            continue
        if not any(call in source for call in _BROWSER_REAL_CHROMIUM_CALLS):
            continue
        pytest.fail(
            f"{item.nodeid} calls warmup() or acquire_page() but lacks "
            "@pytest.mark.integration, e2e, or performance. "
            "Real browser tests must run outside the default suite.",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _reset_approval_denial_state() -> Iterator[None]:
    """Isolate approval denial counters between all tests."""
    with suppress(Exception):
        from myrm_agent_harness.agent.middlewares.approval.helpers import clear_all_session_denials_for_tests

        clear_all_session_denials_for_tests()
    yield
    with suppress(Exception):
        from myrm_agent_harness.agent.middlewares.approval.helpers import clear_all_session_denials_for_tests

        clear_all_session_denials_for_tests()


@pytest.fixture(autouse=True)
def _reset_session_executor_stash() -> Iterator[None]:
    """Isolate the process-global session executor stash between all tests.

    A test that spawns a child under a fixed ``session_id`` and cancels it before
    teardown leaves a stale stashed executor; a later test reusing that id then
    recovers the stale executor instead of exercising the no-executor path.
    """
    with suppress(Exception):
        from myrm_agent_harness.toolkits.code_execution.executors.base import (
            clear_all_stashed_executors_for_tests,
        )

        clear_all_stashed_executors_for_tests()
    yield
    with suppress(Exception):
        from myrm_agent_harness.toolkits.code_execution.executors.base import (
            clear_all_stashed_executors_for_tests,
        )

        clear_all_stashed_executors_for_tests()


@pytest.fixture(autouse=True)
def _restore_chat_id_var() -> Iterator[None]:
    """Isolate the active chat id ContextVar between all tests.

    ``set_approval_session`` writes ``chat_id_var`` in the calling context; a sync
    test that never restores it leaks that id into every later test of the process,
    so code reading the active session (e.g. eviction persistence) sees a stale id
    instead of none.
    """
    from myrm_agent_harness.core.context_vars import chat_id_var

    original = chat_id_var.get()
    yield
    chat_id_var.set(original)


@pytest.fixture(autouse=True)
async def _reset_global_browser_pool_singleton(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Shut down GlobalBrowserPool singleton after browser-related tests.

    ``get_global_browser_pool()`` keeps a module-level instance with a lifecycle
    background task; without teardown, Chromium workers can outlive the test.
    Scoped to browser/integration/e2e paths to avoid async fixture overhead on
    the full ~20k unit-test matrix.
    """
    yield
    if not _needs_browser_singleton_reset(request):
        return

    try:
        from myrm_agent_harness.toolkits.browser.pool import reset_global_browser_pool_for_tests

        with suppress(Exception):
            await reset_global_browser_pool_for_tests()
    except ImportError:
        pass


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
