"""E2E contract: harness recovery events survive server envelope to the UI.

Pins the exact field names the frontend handler reads (freed_tokens,
request_tokens, terminal_code) so a rename on any layer breaks loudly here
instead of silently in production.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from myrm_agent_harness.agent.streaming.recovery.context_pressure_gate import (
    CONTEXT_OVERFLOW_TERMINAL_CODE,
)

HARNESS_ROOT = Path(__file__).resolve().parents[3]
OPEN_PERPLEXITY_ROOT = HARNESS_ROOT.parent
FRONTEND = OPEN_PERPLEXITY_ROOT / "myrm-agent" / "myrm-agent-frontend"
SERVER = OPEN_PERPLEXITY_ROOT / "myrm-agent" / "myrm-agent-server"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_terminal_code_value_is_stable() -> None:
    assert CONTEXT_OVERFLOW_TERMINAL_CODE == "context_overflow_after_compaction"


def test_harness_emits_all_ui_fields() -> None:
    src = _read(
        HARNESS_ROOT / "src" / "myrm_agent_harness" / "agent" / "streaming" / "recovery" / "context_pressure_gate.py"
    )
    for field in ("freed_tokens=", "request_tokens=", "terminal_code="):
        assert field in src, f"harness stopped emitting {field}"


def test_server_envelope_preserves_terminal_code() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.schemas.streaming as s;"
            " e=s.SSEEnvelope(type='context_overflow_reset', messageId='m',"
            " terminal_code='context_overflow_after_compaction');"
            " print(e.to_sse_chunk().strip())",
        ],
        capture_output=True,
        text=True,
        cwd=str(SERVER),
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.removeprefix("data: ").strip())
    assert payload["terminal_code"] == "context_overflow_after_compaction"


def test_frontend_handler_reads_same_fields() -> None:
    handler = _read(FRONTEND / "src" / "store" / "chat" / "messageStream" / "handlers" / "statusStreamProgressSteps.ts")
    for token in (
        "context_preflight_compact",
        "context_presumed_overflow",
        "freed_tokens",
        "request_tokens",
    ):
        assert token in handler, f"frontend stopped reading {token}"


def test_all_locales_cover_new_step_keys() -> None:
    keys = {
        "context_preflight_compact",
        "context_preflight_truncation",
        "context_preflight_exhausted",
        "context_presumed_overflow",
        "context_presumed_overflow_exhausted",
    }
    for locale in ("en", "zh", "zh-TW", "ja", "de", "ko"):
        text = _read(FRONTEND / "locales" / f"{locale}.json")
        missing = {k for k in keys if f'"{k}"' not in text}
        assert not missing, f"{locale}.json missing {sorted(missing)}"
