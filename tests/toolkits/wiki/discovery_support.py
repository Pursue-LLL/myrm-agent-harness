"""Shared stand-ins for the link discovery tests: a scripted chat model, a page writer and a linter factory."""

import re
from collections.abc import Callable
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage

from myrm_agent_harness.toolkits.wiki import WikiConfig, WikiLinter, WikiStructure

CURSOR_KEY = "link_discovery_cursor"
_ARTICLE_RE = re.compile(r"^## Article: (.+)$", re.MULTILINE)


class ScriptedLLM:
    """Chat model stand-in: records every prompt, answers from a script, may act mid-call."""

    def __init__(
        self,
        reply: str | Callable[[str], str] = "[]",
        on_call: Callable[[str], None] | None = None,
    ) -> None:
        self.prompts: list[str] = []
        self._reply = reply
        self._on_call = on_call

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        prompt = str(messages[-1].content)
        self.prompts.append(prompt)
        if self._on_call is not None:
            self._on_call(prompt)
        reply = self._reply(prompt) if callable(self._reply) else self._reply
        return AIMessage(content=reply)

    def articles(self) -> list[str]:
        return [match for prompt in self.prompts for match in _ARTICLE_RE.findall(prompt)]

    def prompt_for(self, key: str) -> str:
        return next(prompt for prompt in self.prompts if f"## Article: {key}\n" in prompt)


def write_page(
    structure: WikiStructure,
    name: str,
    body: str = "Some facts.",
    *,
    status: str | None = None,
    extra_front: str = "",
    tail: str = "",
) -> Path:
    front = "type: concept\n" + (f"publish_status: {status}\n" if status else "") + extra_front
    path = structure.get_concept_file_path(name)
    path.write_text(
        f"---\n{front}---\n\n## Compiled Truth\n{body}\n\n## Timeline\n- 2026-01-01: created\n{tail}",
        encoding="utf-8",
    )
    return path


def make_linter(llm: ScriptedLLM, structure: WikiStructure) -> WikiLinter:
    config = WikiConfig(enable_auto_maintenance=False, enable_backlinks=True)
    return WikiLinter(llm, structure, config)  # type: ignore[arg-type]


def reply_for(key: str, reply: str) -> Callable[[str], str]:
    return lambda prompt: reply if f"## Article: {key}\n" in prompt else "[]"
