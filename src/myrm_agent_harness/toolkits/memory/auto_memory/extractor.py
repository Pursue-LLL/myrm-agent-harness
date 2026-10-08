# [POS]: src/myrm_agent_harness/toolkits/memory/auto_memory/extractor.py
# [INPUT]: Sequence[dict[str, str]], workspace_path, session_id
# [OUTPUT]: SixDimensionalExtractor, SixDimensionalMemorySlice

"""Six-dimensional structured artifact extractor for session memory.

Converts conversation turns into organized memory slices across:
1. workspace_env
2. key_topics
3. user_preferences
4. reusable_knowledge
5. failure_lessons
6. tool_habits
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from typing import Final

from myrm_agent_harness.toolkits.memory.auto_memory.models import SixDimensionalMemorySlice

_PREFERENCE_KEYWORDS: Final[tuple[str, ...]] = (
    "严禁", "必须", "禁止", "要求", "约定", "优先", "规范", "不要", "风格", "红线",
    "must", "never", "always", "prefer", "strictly", "guideline", "rule",
)
_LESSON_KEYWORDS: Final[tuple[str, ...]] = (
    "error", "failed", "failure", "exception", "bug", "traceback", "fix",
    "错误", "失败", "异常", "排查", "修复", "踩坑", "教训", "避坑",
)
_CODE_BLOCK_PATTERN: Final[re.Pattern[str]] = re.compile(r"```(?:\w+)?\n(.*?)```", re.DOTALL)
_TOPIC_EXTRACT_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\w\u4e00-\u9fa5]{3,15}", re.UNICODE)


class SixDimensionalExtractor:
    """Extracts organized six-dimensional memory artifacts from message streams."""

    def extract_slice_heuristic(
        self,
        messages: Sequence[dict[str, str]],
        session_id: str,
        workspace_path: str = "",
    ) -> SixDimensionalMemorySlice:
        """Extract a structured 6D slice using deterministic rule heuristics (0 tokens spent)."""
        topics: set[str] = set()
        user_prefs: list[str] = []
        reusable_facts: list[str] = []
        lessons: list[str] = []
        tool_records: list[str] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content:
                continue

            # Extract user preferences and guidelines from user messages
            if role == "user":
                for sentence in re.split(r"[。\n!?！？]", content):
                    cleaned = sentence.strip()
                    if len(cleaned) < 6:
                        continue
                    if any(kw in cleaned for kw in _PREFERENCE_KEYWORDS):
                        user_prefs.append(cleaned)
                    elif any(kw in cleaned.lower() for kw in _LESSON_KEYWORDS):
                        lessons.append(cleaned)

            # Extract reusable solutions, lessons, and code knowledge from assistant messages
            elif role == "assistant":
                # Detect code blocks
                code_matches = _CODE_BLOCK_PATTERN.findall(content)
                for code_snippet in code_matches:
                    first_line = code_snippet.strip().split("\n")[0]
                    if len(first_line) > 5:
                        reusable_facts.append(f"Snippet pattern: {first_line[:80]}")

                # Detect explanations or bug reflections
                for sentence in re.split(r"[。\n!?！？]", content):
                    cleaned = sentence.strip()
                    if len(cleaned) < 10:
                        continue
                    if any(kw in cleaned.lower() for kw in _LESSON_KEYWORDS):
                        lessons.append(cleaned)

            # Detect tool call messages
            elif role == "tool" or "tool_call" in msg:
                tool_name = msg.get("name") or "generic_tool"
                tool_records.append(f"Invoked tool: {tool_name}")

            # Collect domain topics from all messages
            words = _TOPIC_EXTRACT_PATTERN.findall(content)
            for w in words:
                if len(w) >= 4 and not w.isdigit():
                    topics.add(w)

        # Environment metadata
        workspace_env = workspace_path or "default_workspace"

        # Prune and deduplicate
        final_topics = tuple(sorted(list(topics)[:10]))
        final_prefs = tuple(list(dict.fromkeys(user_prefs))[:8])
        final_knowledge = tuple(list(dict.fromkeys(reusable_facts))[:8])
        final_lessons = tuple(list(dict.fromkeys(lessons))[:8])
        final_tool_habits = tuple(list(dict.fromkeys(tool_records))[:8])

        return SixDimensionalMemorySlice(
            session_id=session_id,
            workspace_env=workspace_env,
            key_topics=final_topics,
            user_preferences=final_prefs,
            reusable_knowledge=final_knowledge,
            failure_lessons=final_lessons,
            tool_habits=final_tool_habits,
            confidence_score=0.95,
            created_at_timestamp=time.time(),
        )

    @staticmethod
    def build_llm_extraction_prompt(
        messages: Sequence[dict[str, str]],
        workspace_path: str = "",
    ) -> str:
        """Construct standard prompt template for LLM-based 6D consolidation."""
        transcript_text = "\n".join(
            f"[{m.get('role', 'unknown')}]: {m.get('content', '').strip()}"
            for m in messages
        )
        return (
            "Analyze the following conversation session and extract a 6-dimensional structured memory artifact:\n"
            f"Workspace: {workspace_path or 'unspecified'}\n\n"
            "Output strictly formatted JSON matching fields:\n"
            "1. workspace_env (string)\n"
            "2. key_topics (array of strings)\n"
            "3. user_preferences (array of strings)\n"
            "4. reusable_knowledge (array of strings)\n"
            "5. failure_lessons (array of strings)\n"
            "6. tool_habits (array of strings)\n\n"
            f"Session Transcript:\n{transcript_text}"
        )
