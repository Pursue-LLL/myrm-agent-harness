"""Artifact-Centric Agent Loop & Dynamic Intent Tracking Engine (Pi Harness v2 Item 26).

Implements the Living-Artifact-Centric paradigm:
1. Living Artifact State Machine:
   Anchors the true working scene in shared, evolvable artifacts (code, documents, diagrams, sheets)
   rather than ephemeral chat turns. Manages artifact versions and lifecycle states.
2. Dynamic Intent Tracking & Action Delta Chain:
   Tracks fine-grained human & agent actions between turns: element selection, direct manual edits,
   semantic annotations, rejection/rollback reasons, and final approvals.
3. Next-Turn Working Scene Hydration:
   Hydrates the latest living state and intent deltas into a compact, lossless prompt context at
   the start of the next turn, eliminating tedious manual user explanations ("I just changed line X").

[INPUT]
- artifact_id: str
- artifact_type: ArtifactType
- content: str
- intent_action: IntentDeltaKind

[OUTPUT]
- ArtifactLifecycleState
- ArtifactType
- LivingArtifactSnapshot
- IntentDeltaKind
- ActorRole
- IntentDeltaRecord
- LivingArtifactStateMachine
- DynamicIntentTracker
- WorkingSceneHydrationPayload
- WorkingSceneHydrator

[POS]
Harness runtime context layer. Elevates artifacts from passive file I/O to first-class working scenes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ArtifactLifecycleState(StrEnum):
    """Lifecycle state of an evolvable working artifact."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STABLE = "stable"


class ArtifactType(StrEnum):
    """Categorization of living artifacts."""

    CODE = "code"
    DOCUMENT = "document"
    CANVAS = "canvas"
    DIAGRAM = "diagram"
    SHEET = "sheet"


class ActorRole(StrEnum):
    """Initiator of an artifact or intent action."""

    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class IntentDeltaKind(StrEnum):
    """Fine-grained user/agent interactions that shape task intent."""

    PROMPT_DIRECTIVE = "prompt_directive"
    ELEMENT_SELECT = "element_select"
    MANUAL_EDIT = "manual_edit"
    ANNOTATION = "annotation"
    REJECT_CHANGE = "reject_change"
    APPROVE_CHANGE = "approve_change"
    ROLLBACK = "rollback"


@dataclass(slots=True, frozen=True)
class LivingArtifactSnapshot:
    """Immutable snapshot of a living artifact at a specific revision."""

    artifact_id: str
    artifact_type: ArtifactType
    name: str
    version: int
    content: str
    content_hash: str
    state: ArtifactLifecycleState
    updated_at: datetime = field(default_factory=datetime.now)
    last_actor: ActorRole = ActorRole.AGENT

    @classmethod
    def create(
        cls,
        artifact_id: str,
        artifact_type: ArtifactType,
        name: str,
        content: str,
        version: int = 1,
        state: ArtifactLifecycleState = ArtifactLifecycleState.DRAFT,
        actor: ActorRole = ActorRole.AGENT,
    ) -> LivingArtifactSnapshot:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return cls(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            name=name,
            version=version,
            content=content,
            content_hash=content_hash,
            state=state,
            last_actor=actor,
        )


@dataclass(slots=True, frozen=True)
class IntentDeltaRecord:
    """A granular intent or interaction delta recorded between conversation turns."""

    delta_id: str
    session_id: str
    artifact_id: str
    actor: ActorRole
    action: IntentDeltaKind
    target_ref: str = ""
    semantic_intent: str = ""
    payload_diff: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class LivingArtifactStateMachine:
    """State machine and revision history manager for living artifacts."""

    def __init__(self) -> None:
        self._artifacts: dict[str, list[LivingArtifactSnapshot]] = {}

    def register_artifact(
        self,
        artifact_id: str,
        artifact_type: ArtifactType,
        name: str,
        initial_content: str,
        actor: ActorRole = ActorRole.AGENT,
    ) -> LivingArtifactSnapshot:
        """Register a new living artifact with initial content."""
        if artifact_id in self._artifacts:
            raise ValueError(f"Artifact '{artifact_id}' is already registered.")
        snapshot = LivingArtifactSnapshot.create(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            name=name,
            content=initial_content,
            version=1,
            state=ArtifactLifecycleState.DRAFT,
            actor=actor,
        )
        self._artifacts[artifact_id] = [snapshot]
        return snapshot

    def get_latest_snapshot(self, artifact_id: str) -> LivingArtifactSnapshot:
        """Fetch the most recent snapshot of an artifact."""
        history = self._artifacts.get(artifact_id)
        if not history:
            raise KeyError(f"Artifact '{artifact_id}' not found.")
        return history[-1]

    def update_content(
        self,
        artifact_id: str,
        new_content: str,
        actor: ActorRole,
        new_state: ArtifactLifecycleState | None = None,
    ) -> LivingArtifactSnapshot:
        """Append a new revision snapshot with updated content and state."""
        current = self.get_latest_snapshot(artifact_id)
        target_state = new_state or current.state
        snapshot = LivingArtifactSnapshot.create(
            artifact_id=artifact_id,
            artifact_type=current.artifact_type,
            name=current.name,
            content=new_content,
            version=current.version + 1,
            state=target_state,
            actor=actor,
        )
        self._artifacts[artifact_id].append(snapshot)
        return snapshot

    def transition_state(
        self,
        artifact_id: str,
        target_state: ArtifactLifecycleState,
        actor: ActorRole,
    ) -> LivingArtifactSnapshot:
        """Transition artifact lifecycle state without altering content."""
        current = self.get_latest_snapshot(artifact_id)
        snapshot = LivingArtifactSnapshot(
            artifact_id=current.artifact_id,
            artifact_type=current.artifact_type,
            name=current.name,
            version=current.version + 1,
            content=current.content,
            content_hash=current.content_hash,
            state=target_state,
            last_actor=actor,
        )
        self._artifacts[artifact_id].append(snapshot)
        return snapshot

    def rollback_to_version(self, artifact_id: str, target_version: int, actor: ActorRole) -> LivingArtifactSnapshot:
        """Rollback artifact to an earlier version, creating a new head snapshot."""
        history = self._artifacts.get(artifact_id)
        if not history:
            raise KeyError(f"Artifact '{artifact_id}' not found.")
        target_snap: LivingArtifactSnapshot | None = None
        for snap in history:
            if snap.version == target_version:
                target_snap = snap
                break
        if not target_snap:
            raise ValueError(f"Version {target_version} does not exist for artifact '{artifact_id}'.")

        current = history[-1]
        rollback_snap = LivingArtifactSnapshot.create(
            artifact_id=artifact_id,
            artifact_type=target_snap.artifact_type,
            name=target_snap.name,
            content=target_snap.content,
            version=current.version + 1,
            state=ArtifactLifecycleState.DRAFT,
            actor=actor,
        )
        history.append(rollback_snap)
        return rollback_snap

    def list_all_artifacts(self) -> list[LivingArtifactSnapshot]:
        """Return the latest snapshot of each registered artifact."""
        return [snaps[-1] for snaps in self._artifacts.values() if snaps]


class DynamicIntentTracker:
    """Tracks human and agent interaction deltas to build a continuous Intent Delta Chain."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._deltas: list[IntentDeltaRecord] = []

    def record_delta(
        self,
        artifact_id: str,
        actor: ActorRole,
        action: IntentDeltaKind,
        *,
        target_ref: str = "",
        semantic_intent: str = "",
        payload_diff: str = "",
    ) -> IntentDeltaRecord:
        """Record an intentional delta between conversation turns."""
        delta_id = f"delta-{len(self._deltas) + 1}-{hashlib.md5(f'{artifact_id}:{datetime.now()}'.encode()).hexdigest()[:8]}"
        record = IntentDeltaRecord(
            delta_id=delta_id,
            session_id=self.session_id,
            artifact_id=artifact_id,
            actor=actor,
            action=action,
            target_ref=target_ref,
            semantic_intent=semantic_intent,
            payload_diff=payload_diff,
        )
        self._deltas.append(record)
        return record

    def get_recent_deltas(self, limit: int = 20) -> list[IntentDeltaRecord]:
        """Retrieve recent interaction deltas ordered chronologically."""
        return list(self._deltas[-limit:])

    def get_unacknowledged_human_deltas(self) -> list[IntentDeltaRecord]:
        """Fetch human deltas that occurred since the last turn."""
        return [d for d in self._deltas if d.actor == ActorRole.USER]


@dataclass(slots=True, frozen=True)
class WorkingSceneHydrationPayload:
    """Lossless working scene context to be injected into the next turn prompt."""

    active_artifacts_count: int
    hydration_summary: str
    formatted_context_block: str
    pending_human_actions_count: int


class WorkingSceneHydrator:
    """Hydrates current living artifacts and intent deltas into next-turn LLM context."""

    @staticmethod
    def hydrate_scene(
        state_machine: LivingArtifactStateMachine,
        intent_tracker: DynamicIntentTracker,
    ) -> WorkingSceneHydrationPayload:
        """Generate a structured working scene context block."""
        artifacts = state_machine.list_all_artifacts()
        recent_deltas = intent_tracker.get_recent_deltas(limit=10)
        human_deltas = [d for d in recent_deltas if d.actor == ActorRole.USER]

        lines: list[str] = [
            "<!-- LIVING-ARTIFACT WORKING SCENE (Auto-Hydrated by Harness) -->",
            "The following living artifacts and human interaction deltas represent the true current working scene.",
            "You MUST base your reasoning on this latest physical state rather than outdated prior turns.",
            "",
            "### Current Living Artifacts:",
        ]

        if not artifacts:
            lines.append("  (None registered)")
        else:
            for art in artifacts:
                lines.append(
                    f"- Artifact '{art.name}' [{art.artifact_type.value}] (id: {art.artifact_id}, "
                    f"v{art.version}, state: {art.state.value}, last modified by: {art.last_actor.value}):"
                )
                # Preview snippet of content
                content_preview = art.content.strip()
                if len(content_preview) > 200:
                    content_preview = content_preview[:200] + "... [truncated preview]"
                lines.append(f"  Snippet: {content_preview!r}")

        lines.append("")
        lines.append("### Recent Intent Delta Chain:")
        if not recent_deltas:
            lines.append("  (No recent interaction deltas)")
        else:
            for d in recent_deltas:
                actor_mark = "👤 User" if d.actor == ActorRole.USER else "🤖 Agent"
                ref_part = f" on '{d.target_ref}'" if d.target_ref else ""
                intent_part = f": {d.semantic_intent}" if d.semantic_intent else ""
                diff_part = f" (diff: {d.payload_diff})" if d.payload_diff else ""
                lines.append(f"- [{actor_mark}] {d.action.value}{ref_part}{intent_part}{diff_part}")

        lines.append("<!-- END LIVING-ARTIFACT WORKING SCENE -->")

        context_block = "\n".join(lines)
        summary = (
            f"Hydrated {len(artifacts)} active artifact(s) and {len(recent_deltas)} intent delta(s) "
            f"({len(human_deltas)} from human user)."
        )

        return WorkingSceneHydrationPayload(
            active_artifacts_count=len(artifacts),
            hydration_summary=summary,
            formatted_context_block=context_block,
            pending_human_actions_count=len(human_deltas),
        )
