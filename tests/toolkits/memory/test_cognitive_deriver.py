import json
from dataclasses import dataclass
from typing import Any

import pytest

from myrm_agent_harness.toolkits.memory.cognitive.deriver import CognitiveDeriver
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


@dataclass
class _FakeNode:
    id: str
    labels: list[str]
    properties: dict[str, Any]


class _FakeGraphStore:
    def __init__(self) -> None:
        self.nodes: list[_FakeNode] = []
        self.relationships: list[tuple[str, str, str, dict[str, Any]]] = []
        self.updated_nodes: list[tuple[str, dict[str, Any]]] = []

    async def get_or_create_node(self, labels: list[str], match_keys: list[str], properties: dict[str, Any]) -> _FakeNode:
        # Create or return existing node
        for node in self.nodes:
            if node.id == properties["id"]:
                return node

        # Mock existing evidence for Claim nodes to allow supersede/contradict
        if "Claim" in labels:
            properties["evidence_count"] = 1

        node = _FakeNode(id=properties["id"], labels=labels, properties=properties)
        self.nodes.append(node)
        return node

    async def create_relationship(self, from_id: str, to_id: str, rel_type: str, properties: dict[str, Any]) -> None:
        self.relationships.append((from_id, to_id, rel_type, properties))

    async def update_node_properties(self, node_id: str, properties: dict[str, Any]) -> None:
        self.updated_nodes.append((node_id, properties))


class _FakeMemoryManager:
    def __init__(self, llm_response: str = "[]") -> None:
        self.stored_memories: list[SemanticMemory] = []
        self.graph_store: _FakeGraphStore | None = _FakeGraphStore()
        self.llm_response = llm_response

    async def _consolidation_llm(self, sys_prompt: str, user_prompt: str) -> str:
        return self.llm_response

    async def store(self, memory: SemanticMemory, _bypass_approval: bool = False) -> SemanticMemory:
        self.stored_memories.append(memory)
        return memory

    async def set_profile_attribute(self, key: str, value: str) -> None:
        self.stored_memories.append(SemanticMemory(content=f"{key}={value}"))

@pytest.mark.asyncio
async def test_cognitive_deriver_core_preference() -> None:
    llm_resp = json.dumps(
        [
            {
                "preference_key": "reply_style",
                "preference_claim": "User wants concise replies",
                "confidence": 0.9,
                "scope": "global",
                "change_kind": "support",
            }
        ]
    )
    manager = _FakeMemoryManager(llm_response=llm_resp)
    deriver = CognitiveDeriver(manager)  # type: ignore

    result = await deriver.run_derivation("sess1", "chat1", [{"role": "user", "content": "Just code"}])

    assert result["success"] is True
    assert result["extracted_count"] == 1

    # One for store(), one for set_profile_attribute()
    assert len(manager.stored_memories) == 2
    assert manager.stored_memories[1].content == "reply_style=User wants concise replies"

@pytest.mark.asyncio
async def test_cognitive_deriver_success() -> None:
    llm_resp = json.dumps(
        [
            {
                "preference_key": "code_only",
                "preference_claim": "User wants only code",
                "confidence": 0.9,
                "scope": "global",
                "change_kind": "supersede",
            }
        ]
    )
    manager = _FakeMemoryManager(llm_response=llm_resp)
    deriver = CognitiveDeriver(manager)  # type: ignore

    result = await deriver.run_derivation("sess1", "chat1", [{"role": "user", "content": "Just code"}])

    assert result["success"] is True
    assert result["extracted_count"] == 1
    assert result["has_disruptive_change"] is True

    assert len(manager.stored_memories) == 1
    mem = manager.stored_memories[0]
    assert isinstance(mem, SemanticMemory)
    assert mem.preference_type == "implicit"
    assert mem.preference_strength == 1.0  # supersede sets to 1.0

    assert manager.graph_store is not None
    assert len(manager.graph_store.nodes) == 2  # Evidence and Claim
    assert len(manager.graph_store.relationships) == 1
    assert manager.graph_store.relationships[0][2] in ("SUPERSEDED_BY", "CONTRADICTED_BY")


@pytest.mark.asyncio
async def test_cognitive_deriver_degradation() -> None:
    llm_resp = json.dumps(
        [
            {
                "preference_key": "code_only",
                "preference_claim": "User wants only code",
                "confidence": 0.85,
                "scope": "global",
                "change_kind": "support",
            }
        ]
    )
    manager = _FakeMemoryManager(llm_response=llm_resp)
    manager.graph_store = None  # Disable graph
    deriver = CognitiveDeriver(manager)  # type: ignore

    result = await deriver.run_derivation("sess1", "chat1", [{"role": "user", "content": "Just code"}])

    assert result["success"] is True
    assert result["extracted_count"] == 1
    assert result["has_disruptive_change"] is False

    assert len(manager.stored_memories) == 1
    mem = manager.stored_memories[0]
    assert mem.preference_strength == 0.85


@pytest.mark.asyncio
async def test_cognitive_deriver_low_confidence() -> None:
    llm_resp = json.dumps(
        [
            {
                "preference_key": "code_only",
                "preference_claim": "User wants only code",
                "confidence": 0.5, # Below 0.8 threshold
                "scope": "global",
                "change_kind": "support",
            }
        ]
    )
    manager = _FakeMemoryManager(llm_response=llm_resp)
    deriver = CognitiveDeriver(manager)  # type: ignore

    result = await deriver.run_derivation("sess1", "chat1", [{"role": "user", "content": "Just code"}])

    assert result["success"] is True
    assert result["extracted_count"] == 0
    assert result["has_disruptive_change"] is False
    assert len(manager.stored_memories) == 0

