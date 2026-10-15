"""`LAYER_EXEMPT_TOOLS` exemptions lapse: they expire, and stale ones must be deleted.

[POS]
tests/architecture/test_tool_registry_exemptions.py

[INPUT]
- scripts.tool_registry_config.LAYER_EXEMPT_TOOLS / LayerExemption
- scripts.tool_registry_models.ScanReport (synthetic reports, no source scan)

[OUTPUT]
- Active exemption hides a declared, unmounted tool; the same tool surfaces once the exemption expired
- Exemptions for undeclared or already registered tools are reported as stale
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts import tool_registry_models
from scripts.tool_registry_config import LayerExemption
from scripts.tool_registry_models import ScanReport, ToolDeclaration

_TOOL = "legacy_probe_tool"
_EXPIRES = date(2027, 1, 31)


def _declaration(name: str) -> ToolDeclaration:
    return ToolDeclaration(name=name, kind="decorator", file=Path("probe.py"), line=1)


@pytest.fixture(autouse=True)
def _exempt_one_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tool_registry_models, "LAYER_EXEMPT_TOOLS", {_TOOL: LayerExemption(_EXPIRES, "kept for a unit test")}
    )


def test_active_exemption_hides_declared_unmounted_tool() -> None:
    report = ScanReport(declarations=[_declaration(_TOOL)])

    assert report.missing_registrations(today=_EXPIRES) == set()
    assert report.layer_exemption_errors(today=_EXPIRES) == []


def test_expired_exemption_surfaces_the_unmounted_tool() -> None:
    report = ScanReport(declarations=[_declaration(_TOOL)])
    day_after = date(2027, 2, 1)

    assert report.missing_registrations(today=day_after) == {_TOOL}
    (error,) = report.layer_exemption_errors(today=day_after)
    assert _TOOL in error
    assert "2027-01-31" in error


def test_exemption_without_declaration_is_stale() -> None:
    (error,) = ScanReport().layer_exemption_errors(today=_EXPIRES)

    assert "no source declares it" in error


def test_exemption_for_registered_tool_is_stale() -> None:
    report = ScanReport(declarations=[_declaration(_TOOL)], registered_names={_TOOL})

    (error,) = report.layer_exemption_errors(today=_EXPIRES)

    assert "now registered" in error
