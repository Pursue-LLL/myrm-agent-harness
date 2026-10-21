from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.artifacts.delight_showcase import (
    SingleFileSandboxEngine,
)


def test_validate_empty_html() -> None:
    engine = SingleFileSandboxEngine()
    result = engine.validate_and_compile("")
    assert not result.is_valid
    assert "cannot be empty" in result.issues[0]


def test_disallow_relative_imports() -> None:
    engine = SingleFileSandboxEngine()
    invalid_html = """
    <script type="module">
      import { myHelper } from "./utils/helper.js";
      console.log(myHelper());
    </script>
    """
    result = engine.validate_and_compile(invalid_html)
    assert not result.is_valid
    assert any("Disallowed relative import" in issue for issue in result.issues)


def test_wrap_partial_canvas_fragment() -> None:
    engine = SingleFileSandboxEngine()
    canvas_fragment = """
    <div class="flex items-center justify-center h-full">
      <canvas id="fireworksCanvas" width="800" height="600"></canvas>
    </div>
    <script>
      const ctx = document.getElementById('fireworksCanvas').getContext('2d');
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    </script>
    """
    result = engine.validate_and_compile(canvas_fragment, title="Programmer Birthday Demo")
    assert result.is_valid
    assert result.has_canvas
    assert result.has_audio
    assert result.has_tailwind
    assert "<!DOCTYPE html>" in result.compiled_html
    assert "viewport" in result.compiled_html
    assert "Programmer Birthday Demo" in result.compiled_html
    assert "cdn.tailwindcss.com" in result.compiled_html


def test_create_sandbox_contract() -> None:
    engine = SingleFileSandboxEngine()
    session_id = "session_delight_001"
    html_source = """
    <!DOCTYPE html>
    <html>
    <head><title>Full Page</title></head>
    <body class="bg-black text-white">
      <h1>Delightful Interactive Card</h1>
    </body>
    </html>
    """
    contract = engine.create_contract(
        session_id=session_id,
        title="Custom Delight Card",
        html_source=html_source,
    )
    assert contract.session_id == session_id
    assert contract.title == "Custom Delight Card"
    assert contract.is_self_contained
    assert contract.contract_id.startswith("sc_")
    assert "viewport" in contract.compiled_html
