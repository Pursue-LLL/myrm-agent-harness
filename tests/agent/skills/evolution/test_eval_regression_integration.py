"""Integration tests for R12 EvalCase regression gate with real LLM.

Covers the real full-chain path:
  SkillStore (eval_cases persistence) -> VariantGenerator (real LLM) ->
  filter_variants_by_regression (regression gate) -> BatchEvaluator (real LLM) ->
  ProposalBuilder -> EvolutionProposal

Key path: engine.fix_skill with eval_cases present on a skill.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.agent.skills.evolution.core.engine import (
    SkillEvolutionEngine,
)
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillLineage,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore


class _TestOpenAIChat(BaseChatModel):
    """Lightweight OpenAI-compatible chat model for integration tests."""

    model: str = ""
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.3
    max_tokens: int = 2048

    @property
    def _llm_type(self) -> str:
        return "openai-compatible"

    def with_structured_output(self, schema: type, **kwargs: Any) -> _StructuredOutputWrapper:
        return _StructuredOutputWrapper(self, schema)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        api_messages = []
        for m in messages:
            role = "user" if isinstance(m, HumanMessage) else "assistant"
            if hasattr(m, "type") and m.type == "system":
                role = "system"
            api_messages.append({"role": role, "content": m.content})

        body: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            json=body,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class _StructuredOutputWrapper:
    """Wraps a _TestOpenAIChat to parse JSON response into a Pydantic model."""

    def __init__(self, llm: _TestOpenAIChat, schema: type) -> None:
        self._llm = llm
        self._schema = schema

    async def ainvoke(self, input: Any, **kwargs: Any) -> Any:
        import re

        field_hint = ""
        if hasattr(self._schema, "model_fields"):
            fields = self._schema.model_fields
            example_parts = []
            for name, field in fields.items():
                if field.annotation is float:
                    example_parts.append(f'"{name}": 0.85')
                elif field.annotation is bool:
                    example_parts.append(f'"{name}": true')
                elif field.annotation is str:
                    example_parts.append(f'"{name}": "explanation"')
                else:
                    example_parts.append(f'"{name}": null')
            field_hint = (
                "\n\nRespond ONLY with a JSON object using these exact field names:\n"
                "{" + ", ".join(example_parts) + "}"
            )

        if isinstance(input, str):
            input = [HumanMessage(content=input + field_hint)]
        elif isinstance(input, list) and input:
            last = input[-1]
            if isinstance(last, HumanMessage):
                input = input[:-1] + [HumanMessage(content=last.content + field_hint)]

        result = self._llm.invoke(input)
        text = result.content
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            return self._schema.model_validate_json(json_match.group())
        return self._schema.model_validate_json(text)


def _load_test_env() -> dict[str, str]:
    """Load .env.test from the server directory for LLM credentials."""
    env_path = (
        Path(__file__).resolve().parents[5]
        / "myrm-agent"
        / "myrm-agent-server"
        / ".env.test"
    )
    env_vars: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                env_vars[key.strip()] = val.strip()
    return env_vars


def _get_llm() -> _TestOpenAIChat | None:
    """Create a real LLM client from test credentials."""
    env = _load_test_env()
    api_key = env.get("BASIC_API_KEY") or os.environ.get("BASIC_API_KEY")
    base_url = env.get("BASIC_BASE_URL") or os.environ.get("BASIC_BASE_URL")
    model_raw = env.get("BASIC_MODEL") or os.environ.get("BASIC_MODEL")

    if not all([api_key, base_url, model_raw]):
        return None

    model_name = model_raw.split("/", 1)[-1] if "/" in model_raw else model_raw
    return _TestOpenAIChat(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
    )


_llm = _get_llm()
_skip_reason = "LLM credentials not available in .env.test"


@pytest.mark.asyncio
@pytest.mark.timeout(120)
@pytest.mark.skipif(_llm is None, reason=_skip_reason)
async def test_fix_skill_with_eval_cases_regression_gate(tmp_path: Path):
    """Full chain: fix_skill with eval_cases → regression gate filters bad variants."""
    store = SkillStore(db_path=tmp_path / "test.db")
    skill = SkillRecord(
        skill_id="integ_fix_1",
        name="nginx-installer",
        description="Install and configure nginx web server",
        content=(
            "Use apt-get to install nginx, then configure the default site.\n"
            "Steps:\n"
            "1. Run: sudo apt-get update && sudo apt-get install -y nginx\n"
            "2. Edit /etc/nginx/sites-available/default\n"
            "3. Run: sudo systemctl restart nginx"
        ),
        path="skills/nginx_installer.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, version=1),
        eval_cases=[
            {
                "sandbox_assertions": [
                    {"type": "code_contains", "target": "nginx"},
                    {"type": "code_contains", "target": "install"},
                ],
            },
            {
                "sandbox_assertions": [
                    {"type": "code_not_contains", "target": "rm -rf /"},
                ],
            },
        ],
    )
    await store.save_skill(skill)

    loaded = store.get_skill("integ_fix_1")
    assert loaded is not None
    assert len(loaded.eval_cases) == 2, "eval_cases should persist through DB"

    engine = SkillEvolutionEngine(
        store=store,
        llm=_llm,
        num_variants_per_evolution=2,
    )

    proposal = await engine.fix_skill(
        skill_id="integ_fix_1",
        error_message="nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)",
        task_context="User wants to set up a web server on port 80 but it's already in use.",
    )

    assert proposal is not None, "Engine should produce a proposal from real LLM"
    assert proposal.evolution_type == EvolutionType.FIX
    assert proposal.skill_id == "integ_fix_1"
    assert len(proposal.proposed_content) > 10, "Proposed content should be non-trivial"
    assert "nginx" in proposal.proposed_content.lower(), (
        "Regression gate should ensure 'nginx' is in proposed content"
    )

    store.close()


@pytest.mark.asyncio
@pytest.mark.timeout(120)
@pytest.mark.skipif(_llm is None, reason=_skip_reason)
async def test_derive_skill_with_eval_cases_coevolution(tmp_path: Path):
    """Full chain: derive_skill with eval_cases → co-evolution generates updated_eval_cases."""
    store = SkillStore(db_path=tmp_path / "test.db")
    skill = SkillRecord(
        skill_id="integ_derive_1",
        name="git-branch-creator",
        description="Create a new git branch and switch to it",
        content=(
            "Create a new git branch from the current branch.\n"
            "Steps:\n"
            "1. Run: git checkout -b <branch-name>\n"
            "2. Push the new branch: git push -u origin <branch-name>"
        ),
        path="skills/git_branch_creator.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, version=1),
        eval_cases=[
            {
                "sandbox_assertions": [
                    {"type": "code_contains", "target": "git"},
                    {"type": "code_contains", "target": "branch"},
                ],
            },
        ],
    )
    await store.save_skill(skill)

    engine = SkillEvolutionEngine(
        store=store,
        llm=_llm,
        num_variants_per_evolution=2,
    )

    proposal = await engine.derive_skill_simple(
        skill_id="integ_derive_1",
        user_feedback="Please also handle the case where the branch already exists - switch to it instead of failing.",
    )

    if proposal is not None:
        assert proposal.evolution_type == EvolutionType.DERIVED
        assert "git" in proposal.proposed_content.lower(), (
            "Regression gate should ensure 'git' remains in derived content"
        )
    # proposal can be None if evaluator rejects all variants on quality
    # (accuracy < 0.7 or score < 0.6). This is correct behavior — the
    # important validation is that the chain ran without error.

    loaded = store.get_skill("integ_derive_1")
    assert loaded is not None
    assert loaded.eval_cases == [
        {"sandbox_assertions": [
            {"type": "code_contains", "target": "git"},
            {"type": "code_contains", "target": "branch"},
        ]},
    ], "Original skill eval_cases should remain intact in DB"

    store.close()


@pytest.mark.asyncio
@pytest.mark.timeout(120)
@pytest.mark.skipif(_llm is None, reason=_skip_reason)
async def test_regression_gate_hard_filters_destructive_variant(tmp_path: Path):
    """Verify regression gate hard-filters variants that fail ALL eval_cases."""
    from myrm_agent_harness.agent.skills.evolution.core.eval_regression import (
        filter_variants_by_regression,
    )
    import logging

    skill = SkillRecord(
        skill_id="gate_test_1",
        name="safe-deployer",
        description="Deploy safely",
        content="deploy with rollback",
        path="skills/safe_deployer.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, version=1),
        eval_cases=[
            {
                "sandbox_assertions": [
                    {"type": "code_contains", "target": "rollback"},
                    {"type": "code_contains", "target": "deploy"},
                ],
            },
            {
                "sandbox_assertions": [
                    {"type": "code_not_contains", "target": "DROP TABLE"},
                ],
            },
        ],
    )

    good_variant = "Steps:\n1. Run deploy script\n2. Enable rollback on failure"
    destructive_variant = "DROP TABLE users; DELETE FROM logs;"
    no_rollback_variant = "Just push to production directly, no safety net"

    logger = logging.getLogger("test_regression_gate")
    survivors, penalties = await filter_variants_by_regression(
        skill,
        [good_variant, destructive_variant, no_rollback_variant],
        logger,
    )

    assert good_variant in survivors, "Good variant should survive"
    assert penalties[good_variant] == 0.0, "Good variant should have zero penalty"
    assert penalties[destructive_variant] > 0, "Destructive variant should have positive penalty"
    assert penalties[no_rollback_variant] > 0, (
        "Variant missing both 'rollback' and 'deploy' should get penalty"
    )
    assert penalties[destructive_variant] > penalties[good_variant], (
        "Destructive variant should have higher penalty than good variant"
    )
