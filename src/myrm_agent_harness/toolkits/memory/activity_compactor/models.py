"""Strongly-typed schemas for Hierarchical Time-Window Activity Compactor pipeline.

[INPUT]
- External: pydantic, datetime, enum

[OUTPUT]
- ActivityActionType: Classification of raw desktop/terminal events.
- RawActivityEvent: Ingested raw low-level activity event.
- MicroActivitySlice: 10-minute algorithmic deduplicated and folded activity slice (0 Token cost).
- MacroMilestoneFold: 6-hour consolidated macro milestone and business achievement.
- DailyPreferenceArchive: 24-hour synthesized long-term preference updates.
- CompactorPipelineTelemetry: Telemetry tracking compression ratio and token savings.
- CompactorPipelineConfig: Configuration parameters for hierarchical compaction windows.

[POS]
Harness framework layer for ChatGPT Desktop Skysight-inspired 10min/6h hierarchical memory pipeline.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ActivityActionType(StrEnum):
    """Classification of raw desktop or terminal actions."""

    APP_SWITCH = "app_switch"
    WINDOW_FOCUS = "window_focus"
    KEYSTROKE_BURST = "keystroke_burst"
    TERMINAL_CMD = "terminal_cmd"
    BROWSER_NAV = "browser_nav"
    IDLE_SILENCE = "idle_silence"


class RawActivityEvent(BaseModel):
    """Low-level raw desktop observation event before compaction."""

    event_id: str = Field(description="Unique event ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Occurrence timestamp")
    app_name: str = Field(description="Application name (e.g., VSCode, Chrome, Terminal)")
    window_title: str = Field(description="Active window title or tab header")
    action_type: ActivityActionType = Field(description="Action category")
    event_payload: str = Field(default="", description="Detailed payload, command text, or URL")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Dwell time in seconds")


class MicroActivitySlice(BaseModel):
    """Algorithmic 10-minute activity slice folded without LLM calls (0 Token cost)."""

    slice_id: str = Field(description="Unique micro slice ID")
    start_time: datetime = Field(description="Slice start timestamp")
    end_time: datetime = Field(description="Slice end timestamp")
    primary_app: str = Field(description="Dominant application during this window")
    raw_event_count: int = Field(ge=0, description="Total raw events ingested into this window")
    folded_summary: str = Field(description="Concise human-readable objective summary of actions")
    unique_windows: list[str] = Field(default_factory=list, description="Unique window titles visited")
    is_idle: bool = Field(default=False, description="Whether this slice was dominated by idle silence")
    active_minutes: float = Field(ge=0.0, description="Active working minutes")


class MacroMilestoneFold(BaseModel):
    """6-hour consolidated macro milestone distilled from ~36 micro slices."""

    fold_id: str = Field(description="Unique macro fold ID")
    start_time: datetime = Field(description="Window start timestamp")
    end_time: datetime = Field(description="Window end timestamp")
    milestone_summary: str = Field(description="Distilled business achievement or project progress")
    key_activities: list[str] = Field(default_factory=list, description="Key work items and milestones achieved")
    micro_slices_count: int = Field(ge=0, description="Number of micro slices aggregated")
    tags: list[str] = Field(default_factory=list, description="Categorization tags (e.g., coding, debugging, review)")
    confidence: float = Field(default=0.95, ge=0.0, le=1.0, description="Consolidation confidence score")


class DailyPreferenceArchive(BaseModel):
    """24-hour long-term synthesized facts and preference updates for persistent memory."""

    archive_id: str = Field(description="Unique daily archive identifier")
    date_str: str = Field(description="ISO Date string YYYY-MM-DD")
    consolidated_facts: list[str] = Field(default_factory=list, description="Verified facts promoted to memory")
    preference_updates: list[str] = Field(default_factory=list, description="Long-term user preference inferences")
    total_raw_events_processed: int = Field(ge=0, description="Total raw events processed throughout the day")
    macro_folds_count: int = Field(ge=0, description="Total macro folds processed")


class CompactorPipelineTelemetry(BaseModel):
    """Telemetry tracking compaction efficacy and token cost savings."""

    total_raw_events: int = Field(default=0, ge=0, description="Total raw events processed")
    total_micro_slices: int = Field(default=0, ge=0, description="Total micro slices generated")
    total_macro_folds: int = Field(default=0, ge=0, description="Total macro folds distilled")
    idle_events_dropped: int = Field(default=0, ge=0, description="Idle or silent events dropped")
    estimated_tokens_saved: int = Field(default=0, ge=0, description="Estimated LLM tokens saved via folding")
    compression_ratio: float = Field(default=0.0, ge=0.0, description="Raw events to distilled items ratio")


class CompactorPipelineConfig(BaseModel):
    """Configuration governing hierarchical sliding windows."""

    micro_window_minutes: int = Field(default=10, ge=1, le=60, description="Micro window size in minutes")
    macro_window_hours: int = Field(default=6, ge=1, le=24, description="Macro window size in hours")
    idle_threshold_seconds: float = Field(default=180.0, ge=30.0, description="Idle silence cutoff threshold")
    max_raw_buffer_size: int = Field(default=1000, ge=100, description="Maximum raw buffer capacity")
