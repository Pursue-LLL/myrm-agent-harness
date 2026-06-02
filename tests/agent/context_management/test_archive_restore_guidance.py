from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.agent.context_management.tracking.archive_restore import build_archive_restore_guidance
from myrm_agent_harness.runtime.execution_paths import get_context_archive_sidecar_path_candidates


def test_context_archive_sidecar_candidates_cover_tool_path_forms() -> None:
    archive_path = ".context/chat/compacted/result.txt"

    candidates = get_context_archive_sidecar_path_candidates(archive_path)

    assert candidates == (
        ".context/chat/compacted/result.txt.restore.json",
        "/persistent/.context/chat/compacted/result.txt.restore.json",
    )


def test_restore_guidance_prefers_restore_map_sidecar(tmp_path: Path) -> None:
    archive_path = tmp_path / "tool_output.txt"
    archive_path.write_text("placeholder", encoding="utf-8")
    sidecar_path = Path(f"{archive_path}.restore.json")
    sidecar_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "archive_path": str(archive_path),
                "recommended_ranges": [
                    f"{archive_path}:41-240",
                    f"{archive_path}:1-200",
                ],
            }
        ),
        encoding="utf-8",
    )

    guidance = build_archive_restore_guidance(str(archive_path), reason="archive_restore_range_required")

    assert guidance.primary_restore_arg == f"{archive_path}:41-240"
    assert guidance.recommended_ranges == (f"{archive_path}:41-240", f"{archive_path}:1-200")
    assert guidance.guidance_source == "restore_map"
    assert guidance.fallback_reason == ""


def test_restore_guidance_reads_restore_map_schema_v2_content_index(tmp_path: Path) -> None:
    archive_path = tmp_path / "tool_output.txt"
    archive_path.write_text("placeholder", encoding="utf-8")
    sidecar_path = Path(f"{archive_path}.restore.json")
    sidecar_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "archive_path": str(archive_path),
                "line_count": 400,
                "content_index": {
                    "line_count": 400,
                    "chunk_size_lines": 200,
                    "chunk_count": 2,
                    "chunk_ranges": [
                        {"start_line": 1, "end_line": 200},
                        {"start_line": 201, "end_line": 400},
                    ],
                },
                "recommended_ranges": [
                    f"{archive_path}:201-400",
                    f"{archive_path}:1-200",
                ],
                "range_sources": [
                    {
                        "range": f"{archive_path}:201-400",
                        "reason": "fallback_chunk",
                        "line": 201,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    guidance = build_archive_restore_guidance(str(archive_path), reason="archive_restore_range_required")

    assert guidance.primary_restore_arg == f"{archive_path}:201-400"
    assert guidance.recommended_ranges == (f"{archive_path}:201-400", f"{archive_path}:1-200")
    assert [hint.to_dict() for hint in guidance.restore_range_hints] == [
        {
            "range_arg": f"{archive_path}:201-400",
            "reason": "fallback_chunk",
            "start_line": 201,
            "end_line": 400,
            "line": 201,
        },
        {
            "range_arg": f"{archive_path}:1-200",
            "reason": "restore_map_range",
            "start_line": 1,
            "end_line": 200,
            "line": 1,
        },
    ]
    assert [feature.to_dict() for feature in guidance.content_features] == [
        {"feature_type": "chunks", "count": 2, "values": []}
    ]
    assert guidance.guidance_source == "restore_map"
    assert guidance.fallback_reason == ""


def test_restore_guidance_falls_back_when_restore_map_invalid(tmp_path: Path) -> None:
    archive_path = tmp_path / "tool_output.txt"
    archive_path.write_text("placeholder", encoding="utf-8")
    Path(f"{archive_path}.restore.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "archive_path": str(archive_path),
                "line_count": 10,
                "recommended_ranges": [f"{archive_path}:11-20"],
            }
        ),
        encoding="utf-8",
    )

    guidance = build_archive_restore_guidance(str(archive_path), reason="archive_restore_range_required")

    assert guidance.primary_restore_arg == f"{archive_path}:1-200"
    assert guidance.restore_range_hints[0].reason == "fallback_chunk"
    assert guidance.restore_range_hints[0].start_line == 1
    assert guidance.restore_range_hints[0].end_line == 200
    assert guidance.guidance_source == "fallback"
    assert guidance.fallback_reason == "restore_map_invalid"


def test_restore_guidance_narrows_fallback_ranges_during_backoff(tmp_path: Path) -> None:
    archive_path = tmp_path / "tool_output.txt"
    archive_path.write_text("placeholder", encoding="utf-8")

    guidance = build_archive_restore_guidance(
        str(archive_path),
        reason="archive_refetch_token_budget_exceeded",
        backoff_adjusted=True,
    )

    assert guidance.primary_restore_arg == f"{archive_path}:1-100"
    assert guidance.recommended_ranges == (f"{archive_path}:1-100",)
    assert guidance.restore_range_hints[0].start_line == 1
    assert guidance.restore_range_hints[0].end_line == 100
    assert guidance.backoff_adjusted is True
    assert guidance.to_dict()["backoff_adjusted"] is True


def test_restore_guidance_resolves_persistent_sidecar_for_context_path(tmp_path: Path) -> None:
    persistent_root = tmp_path / "persistent"
    archive_path = persistent_root / ".context/chat/compacted/result.txt"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text("placeholder", encoding="utf-8")
    Path(f"{archive_path}.restore.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "archive_path": str(archive_path),
                "line_count": 400,
                "recommended_ranges": [f"{archive_path}:201-400"],
            }
        ),
        encoding="utf-8",
    )

    guidance = build_archive_restore_guidance(str(archive_path), reason="archive_restore_range_required")

    assert guidance.primary_restore_arg == f"{archive_path}:201-400"
    assert guidance.guidance_source == "restore_map"
