"""Architecture gate: harness vs external tool layer SSOT."""

from __future__ import annotations

import ast
from pathlib import Path

from myrm_agent_harness.agent.tool_management.tool_layers import ToolLayer, _TOOL_LAYERS

_HARNESS_ROOT = Path(__file__).resolve().parents[2]
_MONOREPO_ROOT = _HARNESS_ROOT.parent
_SERVER_BOOTSTRAP = (
    _MONOREPO_ROOT
    / "myrm-agent"
    / "myrm-agent-server"
    / "app"
    / "ai_agents"
    / "general_agent"
    / "tools"
    / "_tool_layer_bootstrap.py"
)


def _load_server_tool_layers() -> dict[str, str]:
    tree = ast.parse(_SERVER_BOOTSTRAP.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if not isinstance(value, ast.Dict):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "_SERVER_TOOL_LAYERS":
                layers: dict[str, str] = {}
                for key, val in zip(value.keys, value.values, strict=False):
                    if isinstance(key, ast.Constant) and isinstance(val, ast.Attribute):
                        layers[str(key.value)] = val.attr
                return layers
    msg = "Could not parse _SERVER_TOOL_LAYERS from server bootstrap"
    raise AssertionError(msg)


def test_harness_static_layers_exclude_external() -> None:
    for name, layer in _TOOL_LAYERS.items():
        assert layer != ToolLayer.EXTERNAL, f"harness tool {name} must not be EXTERNAL"


def test_server_vendor_layers_are_external() -> None:
    server_layers = _load_server_tool_layers()
    assert server_layers, "server bootstrap must declare vendor tool layers"
    for name, layer in server_layers.items():
        assert layer == "EXTERNAL", f"server vendor tool {name} must be EXTERNAL"
