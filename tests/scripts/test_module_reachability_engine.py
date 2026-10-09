"""Unit tests for scripts.module_reachability_engine.

Every case builds a synthetic package under ``tmp_path`` (root name ``pkg``) so the
tests are hermetic and fast; they neither import the harness nor read its tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.module_reachability_engine import Report, analyze, classify

_HUB = "agent/engine/__init__.py"


def _package(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "pkg"
    for rel, text in {"__init__.py": "", "agent/__init__.py": "", _HUB: "", **files}.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _server(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "server"
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _dead(report: Report) -> set[str]:
    return {unit.key for unit in report.dead}


def test_unit_without_consumer_is_dead(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "agent/engine/used.py": "class Used: ...\n",
            "agent/engine/orphan.py": "class Orphan: ...\n",
            "toolkits/consumer.py": "from pkg.agent.engine.used import Used\n\nUsed()\n",
        },
    )
    assert _dead(analyze(root)) == {"agent/engine/orphan"}


def test_pure_reexport_in_hub_is_not_a_consumer(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            _HUB: 'from .orphan import Orphan\n\n__all__ = ["Orphan"]\n',
            "agent/engine/orphan.py": "class Orphan: ...\n",
        },
    )
    assert _dead(analyze(root)) == {"agent/engine/orphan"}


def test_alias_assignment_in_hub_is_not_a_use(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {_HUB: "from .orphan import Orphan\n\nAlias = Orphan\n", "agent/engine/orphan.py": "class Orphan: ...\n"},
    )
    assert _dead(analyze(root)) == {"agent/engine/orphan"}


def test_real_use_inside_hub_function_makes_unit_live(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            _HUB: "from .helper import build\n\n\ndef make() -> object:\n    return build()\n",
            "agent/engine/helper.py": "def build() -> object: ...\n",
        },
    )
    assert _dead(analyze(root)) == set()


def test_consumer_import_through_hub_binding_is_live(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            _HUB: "from .used import Used\n",
            "agent/engine/used.py": "class Used: ...\n",
            "agent/engine/other.py": "class Other: ...\n",
            "toolkits/consumer.py": "from pkg.agent.engine import Used\n\nUsed()\n",
        },
    )
    assert _dead(analyze(root)) == {"agent/engine/other"}


def test_same_name_without_an_import_is_not_a_consumer(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "agent/engine/orphan.py": "class Orphan: ...\n\n\nSTOP_WORDS = frozenset()\n",
            "toolkits/own.py": "class Orphan: ...\n\n\nSTOP_WORDS = frozenset()\n\nOrphan()\nlen(STOP_WORDS)\n",
            "toolkits/foreign.py": "from third_party import Orphan, STOP_WORDS\n\nOrphan()\nlen(STOP_WORDS)\n",
            "toolkits/attr.py": "def f(obj: object) -> None:\n    obj.Orphan()\n",
        },
    )
    assert _dead(analyze(root)) == {"agent/engine/orphan"}


def test_relative_import_chain_keeps_dependencies_live(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "agent/engine/first.py": "from .second import Second\n\nSecond()\n",
            "agent/engine/second.py": "from . import third\n\nthird.run()\n",
            "agent/engine/third.py": "def run() -> None: ...\n",
            "toolkits/consumer.py": "from pkg.agent.engine.first import First\n",
        },
    )
    assert _dead(analyze(root)) == set()


def test_unit_referenced_only_by_a_dead_unit_is_dead(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "agent/engine/dead_a.py": "from .dead_b import B\n\nB()\n",
            "agent/engine/dead_b.py": "class B: ...\n",
        },
    )
    assert _dead(analyze(root)) == {"agent/engine/dead_a", "agent/engine/dead_b"}


def test_main_module_and_entry_points_are_roots(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "agent/engine/__main__.py": "from .tool import run\n\nrun()\n",
            "agent/engine/tool.py": "def run() -> None: ...\n",
            "agent/engine/cli.py": "def main() -> None: ...\n",
            "agent/engine/unwired.py": "def main() -> None: ...\n",
        },
    )
    assert _dead(analyze(root, entry_points=["pkg.agent.engine.cli:main"])) == {"agent/engine/unwired"}


def test_attribute_chain_on_module_alias_counts(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            _HUB: "from .used import Used\n",
            "agent/engine/used.py": "class Used: ...\n",
            "agent/engine/via_module.py": "def run() -> None: ...\n",
            "agent/engine/orphan.py": "class Orphan: ...\n",
            "toolkits/a.py": "import pkg.agent.engine as eng\n\neng.Used()\n",
            "toolkits/b.py": "import pkg.agent.engine.via_module as vm\n\nvm.run()\n",
            "toolkits/c.py": "import pkg\n\npkg.agent.engine.used.Used()\n",
        },
    )
    assert _dead(analyze(root)) == {"agent/engine/orphan"}


def test_lazy_hub_table_resolves_absolute_and_relative_entries(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            _HUB: (
                "_EXPORTS = {\n"
                '    "Absolute": ("pkg.agent.engine.absolute", "Absolute"),\n'
                '    "Relative": (".relative", "Relative"),\n'
                '    "Unused": (".unused", "Unused"),\n'
                "}\n"
            ),
            "agent/engine/absolute.py": "class Absolute: ...\n",
            "agent/engine/relative.py": "class Relative: ...\n",
            "agent/engine/unused.py": "class Unused: ...\n",
            "toolkits/consumer.py": "from pkg.agent.engine import Absolute, Relative\n",
        },
    )
    assert _dead(analyze(root)) == {"agent/engine/unused"}


def test_hub_without_binding_falls_back_to_exporters_in_its_subtree(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            _HUB: "def __getattr__(name: str) -> object: ...\n",
            "agent/engine/dyn.py": "class Dyn: ...\n",
            "agent/elsewhere/__init__.py": "",
            "agent/elsewhere/twin.py": "class Dyn: ...\n",
            "toolkits/consumer.py": "from pkg.agent.engine import Dyn\n",
        },
    )
    assert _dead(analyze(root)) == {"agent/elsewhere/twin"}


def test_public_surface_reexports_count_but_other_hubs_do_not(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "api/__init__.py": "from pkg.agent.engine.exposed import Exposed\n",
            "toolkits/__init__.py": "from pkg.agent.engine.hidden import Hidden\n",
            "agent/engine/exposed.py": "class Exposed: ...\n",
            "agent/engine/hidden.py": "class Hidden: ...\n",
        },
    )
    assert _dead(analyze(root)) == {"agent/engine/hidden"}


def test_dotted_strings_count_as_references(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "agent/engine/plain.py": "class Plain: ...\n",
            "agent/engine/target.py": "def build() -> None: ...\n",
            "agent/engine/prose.py": "class Prose: ...\n",
            "toolkits/loader.py": (
                'PLAIN = "pkg.agent.engine.plain"\n'
                'TARGET = "pkg.agent.engine.target:build"\n'
                'NOTE = "see pkg.agent.engine.prose for details"\n'
            ),
        },
    )
    assert _dead(analyze(root)) == {"agent/engine/prose"}


def test_server_tree_is_a_consumer_and_reported_separately(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "agent/engine/shared.py": "class Shared: ...\n",
            "agent/engine/server_only.py": "class ServerOnly: ...\n",
            "agent/engine/internal.py": "class Internal: ...\n",
            "toolkits/consumer.py": "from pkg.agent.engine.shared import Shared\n",
        },
    )
    server = _server(
        tmp_path,
        {
            "service.py": "from pkg.agent.engine.server_only import ServerOnly\nfrom .internal import Internal\n",
            "hub/__init__.py": "from pkg.agent.engine.shared import Shared\n",
        },
    )
    report = analyze(root, [server])
    assert _dead(report) == {"agent/engine/internal"}
    assert {unit.key for unit in report.server_only} == {"agent/engine/server_only"}


def test_sub_package_unit_aggregates_inner_modules(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "agent/engine/bundle/__init__.py": "",
            "agent/engine/bundle/inner.py": "def run() -> None: ...\n",
            "agent/standalone.py": "def go() -> None: ...\n",
            "toolkits/consumer.py": "from pkg.agent.engine.bundle.inner import run\n",
        },
    )
    report = analyze(root)
    assert set(report.units) >= {"agent/engine/bundle", "agent/standalone"}
    assert report.units["agent/engine/bundle"].lines >= 2
    assert _dead(report) == {"agent/standalone"}


def test_unparsable_file_is_ignored(tmp_path: Path) -> None:
    root = _package(tmp_path, {"agent/engine/broken.py": "def (:\n", "agent/engine/fine.py": "X = 1\n"})
    assert _dead(analyze(root)) == {"agent/engine/broken", "agent/engine/fine"}


def test_scope_classification() -> None:
    assert classify(("agent", "__init__.py")) == ("root", None)
    assert classify(("agent", "engine", "__init__.py")) == ("root", None)
    assert classify(("agent", "engine", "__main__.py")) == ("root", None)
    assert classify(("toolkits", "memory", "store.py")) == ("root", None)
    assert classify(("core", "standalone.py")) == ("unit", "core/standalone")
    assert classify(("runtime", "context", "engine.py")) == ("unit", "runtime/context/engine")
    assert classify(("runtime", "context", "bundle", "deep", "mod.py")) == ("unit", "runtime/context/bundle")
