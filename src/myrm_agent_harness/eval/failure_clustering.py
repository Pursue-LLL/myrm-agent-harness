"""Failure Signature (ci, qi, mi) Clustering & Dual-Axis Addressability Engine.

[INPUT]
- protocols::EvalTurnResult, EvalResult (POS: evaluation trajectory models)
- trajectory_analysis::FailureMode, analyze_turn_failure_mode (POS: root-cause failure classifier)

[OUTPUT]
- AddressabilityVerdict: ADDRESSABLE, MODEL_LIMIT, FLAKE
- FailureSignature: normalized error descriptor (ci, qi, mi)
- ProfilePatchProposal: RFC-6902 compliant JSON Patch proposal with explanation
- SignatureCluster: aggregated cluster of recurring failure signatures
- sanitize_failure_fingerprint(): Sentry-grade regex sanitization of dynamic trace variables
- cluster_failure_signatures(): deterministic failure signature clustering & patch derivation

[POS]
Translates disparate evaluation failure traces into actionable, normalized clusters.
Evaluates dual-axis addressability (failure signature ci × model capability tier mi)
and synthesizes executable RFC-6902 configuration patches without requiring extra LLM calls.
"""

from __future__ import annotations

import enum
import hashlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

from .trajectory_analysis import FailureMode, analyze_turn_failure_mode

if TYPE_CHECKING:
    from .protocols import EvalResult, EvalTurnResult


class AddressabilityVerdict(enum.StrEnum):
    """Dual-axis addressability classification for failure signatures."""

    ADDRESSABLE = "addressable"  # Fixable via harness middleware, tool binding, or policy
    MODEL_LIMIT = "model_limit"  # Inherent model reasoning ceiling (route to stronger model)
    FLAKE = "flake"  # Transient timeout, rate limit, or environment instability


# Sanitization regexes for Sentry-grade fingerprint normalization
_RE_HEX_ADDRESS = re.compile(r"0x[0-9a-fA-F]{4,16}")
_RE_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_RE_PYTHON_STACK_LOC = re.compile(r'File\s+"[^"]+",\s+line\s+\d+', re.IGNORECASE)
_RE_TEMP_PATH = re.compile(r"(/[\w.-]+)*/(tmp|temp|var/folders)/[\w.-/]+")
_RE_LINE_NUM = re.compile(r"\bline\s+\d+\b", re.IGNORECASE)
_RE_WHITESPACE = re.compile(r"\s+")


def sanitize_failure_fingerprint(raw_text: str) -> str:
    """Normalize raw error traces by stripping volatile runtime tokens.

    Removes memory pointers, UUIDs, temporary file paths, and exact line numbers
    to prevent cluster over-fragmentation.
    """
    if not raw_text:
        return "unknown_error"

    text = _RE_HEX_ADDRESS.sub("<HEX_ADDR>", raw_text)
    text = _RE_UUID.sub("<UUID>", text)
    text = _RE_PYTHON_STACK_LOC.sub('File "<LOC>"', text)
    text = _RE_TEMP_PATH.sub("<TEMP_PATH>", text)
    text = _RE_LINE_NUM.sub("line <N>", text)
    text = _RE_WHITESPACE.sub(" ", text).strip()
    return text[:300]


def extract_query_intent(message: str) -> str:
    """Heuristic intent domain (qi) extractor from case message."""
    msg = message.lower()
    if any(k in msg for k in ("search", "find online", "http", "google", "fetch", "web")):
        return "web_search"
    if any(k in msg for k in ("select ", "sql", "query", "database", "table")):
        return "sql_query"
    if any(k in msg for k in ("def ", "class ", "python", "typescript", "code", "function", "bug", "fix")):
        return "code_generation"
    if any(k in msg for k in ("math", "calculate", "prove", "theorem", "equation")):
        return "math_reasoning"
    if any(k in msg for k in ("read file", "write file", "disk", "directory", "save", "delete")):
        return "file_io"
    return "general_task"


def is_weak_model_tier(model_id: str) -> bool:
    """Determine if a model is in a compact/weak parameter tier."""
    m = model_id.lower()
    return any(k in m for k in ("7b", "8b", "3b", "1.5b", "mini", "flash", "haiku", "small"))


@dataclass(frozen=True, slots=True)
class FailureSignature:
    """Structured failure signature tuple (ci, qi, mi)."""

    ci: str  # Context/sanitized failure fingerprint
    qi: str  # Query/task intent category
    mi: str  # Execution model identifier
    failure_mode: FailureMode

    @property
    def fingerprint_hash(self) -> str:
        raw = f"{self.failure_mode.value}|{self.ci}|{self.qi}|{self.mi}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class ProfilePatchProposal:
    """RFC-6902 compliant JSON patch proposal for Agent configuration."""

    op: str  # "add", "replace", "remove"
    path: str  # RFC-6902 JSON pointer e.g. "/capabilities/tool_repair"
    value: object
    rationale: str
    target_component: str

    def to_dict(self) -> dict[str, object]:
        return {
            "op": self.op,
            "path": self.path,
            "value": self.value,
            "rationale": self.rationale,
            "target_component": self.target_component,
        }


@dataclass(slots=True)
class SignatureCluster:
    """Aggregated cluster of failure signatures across evaluation turns."""

    cluster_id: str
    signature: FailureSignature
    verdict: AddressabilityVerdict
    affected_case_indices: list[int] = field(default_factory=list)
    sample_messages: list[str] = field(default_factory=list)
    remediation_hint: str = ""
    patch_proposal: ProfilePatchProposal | None = None

    @property
    def case_count(self) -> int:
        return len(self.affected_case_indices)

    def to_dict(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "ci": self.signature.ci,
            "qi": self.signature.qi,
            "mi": self.signature.mi,
            "failure_mode": self.signature.failure_mode.value,
            "verdict": self.verdict.value,
            "case_count": self.case_count,
            "affected_case_indices": list(self.affected_case_indices),
            "sample_messages": list(self.sample_messages),
            "remediation_hint": self.remediation_hint,
            "patch_proposal": self.patch_proposal.to_dict() if self.patch_proposal else None,
        }


def _derive_patch_and_verdict(
    sig: FailureSignature,
) -> tuple[AddressabilityVerdict, str, ProfilePatchProposal | None]:
    """Dual-axis decision matrix determining addressability and synthesizing RFC-6902 patch."""
    ci_lower = sig.ci.lower()
    is_weak = is_weak_model_tier(sig.mi)

    # 1. Tool argument serialization issues -> Addressable via tool argument repair middleware
    if sig.failure_mode == FailureMode.TOOL_ARGUMENT_MALFORMED:
        return (
            AddressabilityVerdict.ADDRESSABLE,
            "Model parameters failed JSON/type serialization. Enable tool argument repair middleware.",
            ProfilePatchProposal(
                op="replace",
                path="/capabilities/tool_repair/enabled",
                value=True,
                rationale="Auto-repair unescaped quotes and minor schema deviations",
                target_component="middleware",
            ),
        )

    # 2. Context Overflow -> Addressable via context compression middleware
    if sig.failure_mode == FailureMode.CONTEXT_OVERFLOW_OR_BUDGET:
        return (
            AddressabilityVerdict.ADDRESSABLE,
            "Trajectory exhausted turn or token budget. Enable context window compression.",
            ProfilePatchProposal(
                op="replace",
                path="/capabilities/context_compression/enabled",
                value=True,
                rationale="Enable adaptive sliding window compaction to avoid token overflow",
                target_component="middleware",
            ),
        )

    # 3. Tool Selection Error -> Addressable if missing core tools
    if sig.failure_mode == FailureMode.TOOL_SELECTION_ERROR:
        return (
            AddressabilityVerdict.ADDRESSABLE,
            "Agent failed to locate required tools. Check tool definitions and skill bindings.",
            ProfilePatchProposal(
                op="add",
                path="/capabilities/skills/-",
                value="recommended_domain_skill",
                rationale="Bind missing domain skill to agent capabilities catalog",
                target_component="tool",
            ),
        )

    # 4. Intent Misunderstanding / Complex Math / Logic
    if sig.failure_mode == FailureMode.INTENT_MISUNDERSTANDING:
        if is_weak and sig.qi in ("math_reasoning", "code_generation"):
            # Model limitation: do NOT clutter prompt
            return (
                AddressabilityVerdict.MODEL_LIMIT,
                f"Model '{sig.mi}' reached cognitive reasoning ceiling on {sig.qi}. Route to reasoning model.",
                ProfilePatchProposal(
                    op="replace",
                    path="/model_routing/complex_reasoning_model",
                    value="deepseek-r1",
                    rationale="Route high-complexity multi-step reasoning to frontier reasoning models",
                    target_component="router",
                ),
            )
        return (
            AddressabilityVerdict.ADDRESSABLE,
            "Intent contract violated. Clarify task boundary constraints in system instructions.",
            ProfilePatchProposal(
                op="add",
                path="/persona/constraints/-",
                value="Explicitly verify output format before finalizing answer",
                rationale="Add minimal output format self-verification instruction",
                target_component="prompt",
            ),
        )

    # 5. Execution Timeout
    if sig.failure_mode == FailureMode.EXECUTION_TIMEOUT:
        if any(term in ci_lower for term in ("rate limit", "503", "connection", "connect")):
            return (
                AddressabilityVerdict.FLAKE,
                "Transient network failure or upstream provider rate limit. Retry test without edits.",
                None,
            )
        return (
            AddressabilityVerdict.ADDRESSABLE,
            "Execution exceeded time limit. Increase step timeout or sandbox budget.",
            ProfilePatchProposal(
                op="replace",
                path="/execution/timeout_seconds",
                value=120,
                rationale="Increase per-step execution timeout threshold",
                target_component="middleware",
            ),
        )

    # 6. Destructive or regressive actions
    if sig.failure_mode == FailureMode.DESTRUCTIVE_OR_REGRESSIVE:
        return (
            AddressabilityVerdict.ADDRESSABLE,
            "Agent attempted destructive edits. Enforce workspace safety interceptors.",
            ProfilePatchProposal(
                op="replace",
                path="/security/workspace_guard/enabled",
                value=True,
                rationale="Enforce workspace worktree rollback protection before executing dangerous edits",
                target_component="middleware",
            ),
        )

    # Default fallback
    return (
        AddressabilityVerdict.ADDRESSABLE,
        f"Diagnosed failure under {sig.failure_mode.value}. Review detailed trajectory evidence.",
        None,
    )


def cluster_failure_signatures(
    eval_result: EvalResult,
    max_clusters: int = 10,
) -> list[SignatureCluster]:
    """Group failed evaluation turns into normalized (ci, qi, mi) clusters.

    Sorts clusters by impacted case count descending and derives RFC-6902 patch proposals.
    """
    model_id = (
        eval_result.manifest.model_id
        if eval_result.manifest and eval_result.manifest.model_id
        else "unknown_model"
    )

    clusters_by_key: dict[str, SignatureCluster] = {}

    for idx, turn in enumerate(eval_result.turn_results):
        analysis = analyze_turn_failure_mode(turn)
        if analysis is None:
            continue

        # 1. Sanitize raw error string
        raw_err = turn.error or turn.assertion_details or analysis.evidence_snippet or ""
        clean_ci = sanitize_failure_fingerprint(str(raw_err))

        # 2. Extract query intent
        case_msg = turn.case.message if turn.case else ""
        qi = extract_query_intent(case_msg)

        # 3. Build failure signature
        sig = FailureSignature(
            ci=clean_ci,
            qi=qi,
            mi=model_id,
            failure_mode=analysis.failure_mode,
        )

        cluster_key = f"{sig.failure_mode.value}|{sig.ci}|{sig.qi}|{sig.mi}"

        if cluster_key not in clusters_by_key:
            verdict, hint, patch = _derive_patch_and_verdict(sig)
            clusters_by_key[cluster_key] = SignatureCluster(
                cluster_id=sig.fingerprint_hash,
                signature=sig,
                verdict=verdict,
                remediation_hint=hint,
                patch_proposal=patch,
            )

        c = clusters_by_key[cluster_key]
        c.affected_case_indices.append(idx)
        if len(c.sample_messages) < 3 and case_msg:
            c.sample_messages.append(case_msg[:120])

    # Sort clusters by impact count descending
    sorted_clusters = sorted(
        clusters_by_key.values(),
        key=lambda cl: cl.case_count,
        reverse=True,
    )

    return sorted_clusters[:max_clusters]
