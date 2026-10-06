"""Unit tests for structured checkpoint generator and deterministic file I/O tracker.

Verifies:
1. Deterministic file I/O extraction (reads, writes, artifacts) from message histories.
2. Output token budget calculator bounds and min floors.
3. 6-Dimensional checkpoint contract serialization and Markdown rendering.
4. Incremental previous-summary prompt evolution and additional-focus directive injection.
5. Robust parsing and fault tolerance across JSON variations.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.runtime.context.file_io_checkpoint_tracker import (
    DeterministicFileIOSummary,
    extract_deterministic_file_io,
    normalize_clean_path,
)
from myrm_agent_harness.runtime.context.structured_checkpoint_generator import (
    StructuredCheckpointContract,
    build_checkpoint_prompt,
    compute_summary_max_output_tokens,
    create_checkpoint_from_messages,
    parse_checkpoint_contract,
)


def test_normalize_clean_path() -> None:
    assert normalize_clean_path("./src/foo/bar.py") == "src/foo/bar.py"
    assert normalize_clean_path("/app/models/user.py") == "app/models/user.py"
    assert normalize_clean_path(r".\windows\path\file.ts") == "windows/path/file.ts"
    assert normalize_clean_path("") == ""


def test_deterministic_file_io_summary_markdown() -> None:
    empty_summary = DeterministicFileIOSummary()
    assert empty_summary.is_empty() is True
    assert "Files Read: None" in empty_summary.to_markdown()
    assert "Files Modified: None" in empty_summary.to_markdown()

    populated = DeterministicFileIOSummary(
        files_read=["src/main.py", "tests/test_main.py"],
        files_modified=["src/utils.py"],
        artifacts_created=["report.md"],
    )
    assert populated.is_empty() is False
    md = populated.to_markdown()
    assert "src/main.py" in md
    assert "src/utils.py" in md
    assert "report.md" in md
    assert "do NOT reread unless modified" in md


def test_extract_deterministic_file_io_from_messages() -> None:
    messages = [
        HumanMessage(content="Please inspect the project structure and edit auth.py"),
        AIMessage(
            content="Reading config and viewing files",
            tool_calls=[
                {
                    "name": "view_file",
                    "args": {"AbsolutePath": "/workspace/config.yaml"},
                    "id": "c1",
                },
                {
                    "name": "read_file",
                    "args": {"target_file": "/workspace/src/auth.py"},
                    "id": "c2",
                },
            ],
        ),
        ToolMessage(content="content of config", name="view_file", tool_call_id="c1"),
        ToolMessage(content="content of auth.py", name="read_file", tool_call_id="c2"),
        AIMessage(
            content="Modifying auth.py and creating an artifact",
            tool_calls=[
                {
                    "name": "replace_file_content",
                    "args": {"TargetFile": "/workspace/src/auth.py", "Instruction": "fix bug"},
                    "id": "c3",
                },
                {
                    "name": "write_to_file",
                    "args": {
                        "TargetFile": "/workspace/artifacts/plan.md",
                        "ArtifactMetadata": {"Summary": "Execution Plan", "UserFacing": True},
                    },
                    "id": "c4",
                },
            ],
        ),
        ToolMessage(content="replaced", name="replace_file_content", tool_call_id="c3"),
        ToolMessage(
            content="created",
            name="write_to_file",
            tool_call_id="c4",
            artifact={"path": "/workspace/artifacts/plan.md"},
        ),
    ]

    summary = extract_deterministic_file_io(messages)
    assert "workspace/config.yaml" in summary.files_read
    assert "workspace/src/auth.py" in summary.files_read
    assert "workspace/src/auth.py" in summary.files_modified
    assert "workspace/artifacts/plan.md" in summary.files_modified
    assert "workspace/artifacts/plan.md" in summary.artifacts_created


def test_compute_summary_max_output_tokens() -> None:
    # Default: min(floor(16384 * 0.8), 4096) = min(13107, 4096) = 4096
    assert compute_summary_max_output_tokens(reserve_tokens=16384, model_max_tokens=4096) == 4096

    # Smaller model output cap: min(13107, 2048) = 2048
    assert compute_summary_max_output_tokens(reserve_tokens=16384, model_max_tokens=2048) == 2048

    # Small reserve tokens: floor(2000 * 0.8) = 1600 < 4096 => 1600
    assert compute_summary_max_output_tokens(reserve_tokens=2000, model_max_tokens=4096) == 1600

    # Minimum floor check: 400 * 0.8 = 320 < 512 => 512
    assert compute_summary_max_output_tokens(reserve_tokens=400, model_max_tokens=4096) == 512


def test_structured_checkpoint_contract_to_dict_and_markdown() -> None:
    file_io = DeterministicFileIOSummary(
        files_read=["app/core.py"],
        files_modified=["app/api.py"],
        artifacts_created=["design.png"],
    )
    contract = StructuredCheckpointContract(
        goal="Migrate authentication service to OAuth2",
        constraints_and_preferences=["No breaking API changes", "Use async/await"],
        progress=["Refactored auth middleware", "Added token validation"],
        key_decisions=["Selected JWT with RS256 over HS256 for cross-service verification"],
        next_steps=["Implement refresh token rotation", "Run e2e auth tests"],
        critical_context=["AUTH_SERVICE_PORT=8080", "Keycloak realm: production"],
        file_io=file_io,
        additional_focus="Ensure Keycloak token rotation is documented",
    )

    d = contract.to_dict()
    assert d["goal"] == "Migrate authentication service to OAuth2"
    assert d["files_read"] == ["app/core.py"]
    assert d["files_modified"] == ["app/api.py"]
    assert d["additional_focus"] == "Ensure Keycloak token rotation is documented"

    md = contract.to_markdown()
    assert "**Goal**: Migrate authentication service to OAuth2" in md
    assert "**Focused Directive**: Ensure Keycloak token rotation is documented" in md
    assert "## Constraints & Preferences" in md
    assert "No breaking API changes" in md
    assert "## Key Architecture Decisions" in md
    assert "Selected JWT with RS256" in md
    assert "## Next Steps" in md
    assert "Implement refresh token rotation" in md
    assert "## Critical Technical Context" in md
    assert "AUTH_SERVICE_PORT=8080" in md
    assert "[Deterministic File & Artifact Manifest]" in md


def test_build_checkpoint_prompt_full_and_incremental() -> None:
    # 1. Full mode without previous summary
    prompt_full = build_checkpoint_prompt(
        conversation_text="User: Fix the bug\nAssistant: Fixed.",
        previous_summary=None,
        additional_focus="",
    )
    assert "6-Dimensional Checkpoint" in prompt_full
    assert "[PREVIOUS-SUMMARY ANCHOR" not in prompt_full
    assert "[CRITICAL ADDITIONAL FOCUS" not in prompt_full

    # 2. Incremental mode with previous summary and focus
    prev = StructuredCheckpointContract(
        goal="Build checkout page",
        progress=["Created payment form"],
        key_decisions=["Use Stripe SDK"],
    )
    prompt_incr = build_checkpoint_prompt(
        conversation_text="User: Add PayPal option\nAssistant: Added.",
        previous_summary=prev,
        additional_focus="Pay attention to PayPal sandbox credentials",
    )
    assert "[PREVIOUS-SUMMARY ANCHOR - INCREMENTAL UPDATE MODE]" in prompt_incr
    assert "Build checkout page" in prompt_incr
    assert '[CRITICAL ADDITIONAL FOCUS: "Pay attention to PayPal sandbox credentials"]' in prompt_incr
    assert "dedicating roughly 60-70% of the summary detail" in prompt_incr


def test_parse_checkpoint_contract_success_and_fallback() -> None:
    # Valid JSON
    valid_payload = json.dumps(
        {
            "goal": "Refactor database models",
            "constraints_and_preferences": ["Must use SQLAlchemy 2.0 syntax"],
            "progress": ["Updated User model", "Updated Post model"],
            "key_decisions": ["Switched from declarative_base to DeclarativeBase"],
            "next_steps": ["Run alembic migrations"],
            "critical_context": ["DATABASE_URL=sqlite:///test.db"],
        }
    )
    contract = parse_checkpoint_contract(f"```json\n{valid_payload}\n```", additional_focus="SQLAlchemy")
    assert contract.goal == "Refactor database models"
    assert contract.constraints_and_preferences == ["Must use SQLAlchemy 2.0 syntax"]
    assert contract.key_decisions == ["Switched from declarative_base to DeclarativeBase"]
    assert contract.additional_focus == "SQLAlchemy"

    # Fallback with raw text / broken JSON
    broken_payload = "I am summarizing this: goal is to clean up logs. Some details."
    fallback_contract = parse_checkpoint_contract(broken_payload)
    assert fallback_contract.goal == "Maintain task continuity and complete active requests."
    assert isinstance(fallback_contract.progress, list)


def test_create_checkpoint_from_messages_helper() -> None:
    messages = [
        HumanMessage(content="Hello"),
        AIMessage(
            content="Looking at code",
            tool_calls=[{"name": "view_file", "args": {"path": "/app/service.py"}, "id": "1"}],
        ),
    ]
    prompt, file_io = create_checkpoint_from_messages(
        messages,
        additional_focus="Check service exception handling",
    )
    assert "app/service.py" in file_io.files_read
    assert '[CRITICAL ADDITIONAL FOCUS: "Check service exception handling"]' in prompt
