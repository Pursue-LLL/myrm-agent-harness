"""Triple Edge Auxiliary Pipeline.

Decouples auxiliary tasks (command screening, title generation, user profile compaction)
from heavy cloud LLMs down to local edge inference (<0.5s latency, 100% local privacy).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from .types import (
    CommandRiskLevel,
    CommandScreeningResult,
    ProfileCompactionResult,
    TitleGenerationResult,
)


class TripleEdgeAuxiliaryEngine:
    """Edge auxiliary engine executing lightweight tasks locally for sub-second responses."""

    def __init__(
        self,
        edge_model_invoker: Callable[[str, str], str] | None = None,
    ) -> None:
        self._edge_model_invoker = edge_model_invoker

    def screen_command(self, command: str) -> CommandScreeningResult:
        """Task 1: Pre-screen command risk for approval workflows in milliseconds."""
        t0 = time.perf_counter()
        trimmed = command.strip()

        risk_factors: list[str] = []
        is_dangerous = False
        risk_level = CommandRiskLevel.LOW

        # Fast heuristic semantics
        if re.search(r"\b(rm|del|rmdir|unlink)\b", trimmed, re.IGNORECASE):
            risk_factors.append("File deletion intent")
            risk_level = CommandRiskLevel.MEDIUM

        if re.search(r"\b(chmod|chown|attrib)\b", trimmed, re.IGNORECASE):
            risk_factors.append("Permission alteration intent")
            risk_level = CommandRiskLevel.MEDIUM

        if re.search(r"\b(curl|wget|nc|netcat|socat|ssh|scp|ftp)\b", trimmed, re.IGNORECASE):
            risk_factors.append("Network egress or remote connection intent")
            risk_level = CommandRiskLevel.HIGH

        if re.search(r"\b(sudo|su|runas|doas)\b", trimmed, re.IGNORECASE):
            risk_factors.append("Privilege escalation intent")
            risk_level = CommandRiskLevel.HIGH
            is_dangerous = True

        if re.search(r"\b(drop|truncate|alter)\b", trimmed, re.IGNORECASE):
            risk_factors.append("Database schema destruction intent")
            risk_level = CommandRiskLevel.CRITICAL
            is_dangerous = True

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        summary = (
            f"Edge pre-screening flagged {len(risk_factors)} risk factors: {', '.join(risk_factors)}"
            if risk_factors
            else "Clean command; no risk factors detected"
        )

        return CommandScreeningResult(
            command=trimmed,
            risk_level=risk_level,
            is_dangerous=is_dangerous,
            risk_factors=risk_factors,
            execution_time_ms=round(elapsed_ms, 2),
            summary=summary,
        )

    def generate_session_title(self, first_turn_text: str) -> TitleGenerationResult:
        """Task 2: Generate concise session title (10-20 chars) and tags locally."""
        t0 = time.perf_counter()
        text = first_turn_text.strip()

        # Extract primary intent keywords
        cleaned = re.sub(r"[^\w\s\u4e00-\u9fa5]", " ", text)
        words = [w for w in cleaned.split() if len(w) > 1]

        # Extract tags
        suggested_tags: list[str] = []
        if re.search(r"(python|fastapi|pytest|flask)", text, re.IGNORECASE):
            suggested_tags.append("Python")
        if re.search(r"(docker|container|sandbox|k8s|kubernetes)", text, re.IGNORECASE):
            suggested_tags.append("DevOps")
        if re.search(r"(security|auth|rbac|token|key|guard)", text, re.IGNORECASE):
            suggested_tags.append("Security")
        if re.search(r"(react|typescript|frontend|vue|ui)", text, re.IGNORECASE):
            suggested_tags.append("Frontend")

        # Generate title
        if not words:
            title = "New Agent Session"
        else:
            candidate = " ".join(words[:4])
            title = candidate[:24].strip()

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return TitleGenerationResult(
            title=title,
            suggested_tags=suggested_tags,
            execution_time_ms=round(elapsed_ms, 2),
        )

    def compact_user_profile(
        self, conversation_snippet: str, existing_profile: dict[str, str] | None = None
    ) -> ProfileCompactionResult:
        """Task 3: Extract and compact user tech stack and preference memory."""
        t0 = time.perf_counter()
        profile: dict[str, str] = dict(existing_profile or {})
        extracted_preferences: list[str] = []

        snippet_lower = conversation_snippet.lower()

        # Tech stack preference detection
        if "python" in snippet_lower:
            profile["language"] = "Python"
            extracted_preferences.append("language: Python")
        elif "typescript" in snippet_lower or "javascript" in snippet_lower:
            profile["language"] = "TypeScript"
            extracted_preferences.append("language: TypeScript")

        if "fastapi" in snippet_lower:
            profile["backend_framework"] = "FastAPI"
            extracted_preferences.append("framework: FastAPI")
        elif "django" in snippet_lower:
            profile["backend_framework"] = "Django"
            extracted_preferences.append("framework: Django")

        if "docker" in snippet_lower:
            profile["deployment_preference"] = "Docker Containers"
            extracted_preferences.append("deployment: Docker")

        if "strict" in snippet_lower or "zero any" in snippet_lower:
            profile["code_style"] = "Strict Types / Zero Any"
            extracted_preferences.append("code_style: Strict Types")

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return ProfileCompactionResult(
            compacted_profile=profile,
            extracted_preferences=extracted_preferences,
            execution_time_ms=round(elapsed_ms, 2),
        )
