"""[POS]: tests/unit/toolkits/memory/test_progressive_sidecar_suite.py
[INPUT]: Long-form markdown documents, ContextVirtualFileSystem instance, and tier requests.
[OUTPUT]: Pytest unit test suite verifying L0/L1/L2 sidecar extraction, bundle generation, and tiered disclosure.
"""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory import (
    ContextTier,
    ContextVirtualFileSystem,
    ProgressiveContextVFSAdapter,
    ProgressiveSidecarEngine,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_sidecar.db"


SAMPLE_LONG_DOC = """# Distributed Memory Architecture ADR 042

This document specifies the authoritative design for the multi-tier memory hierarchy in autonomous agent clusters.
The system guarantees deterministic consensus across disparate compute nodes while maintaining strict token efficiency.

## 1. Core Architectural Tenets
- **High Concurrency**: The memory bus must support 10,000 queries per second without lock contention.
- **Strict Data Consistency**: Distributed state machine replication ensures zero stale read hazards.
- **Progressive Disclosure**: Agents must not ingest full transcripts when abstract summaries suffice.

## 2. Interface Contracts
```python
class DistributedMemoryNode:
    def commit_transaction(self, tx_id: str) -> bool:
        pass

    async def broadcast_heartbeat(self) -> None:
        pass
```

## 3. Subsystem Implementation Details
Every transaction is partitioned into shards based on consistent hashing of the tenant identifier.
When a worker executes an update, it acquires a lease with a monotonic epoch token.
If the lease expires, the coordinator automatically revokes the lock and rolls back uncommitted changes.
"""


def test_sidecar_engine_heuristic_extraction() -> None:
    # 1. Test L0 abstract extraction
    l0 = ProgressiveSidecarEngine.extract_l0_abstract(SAMPLE_LONG_DOC, max_tokens=100)
    assert "This document specifies the authoritative design" in l0
    assert len(l0.split()) < 80

    # 2. Test L1 overview extraction
    l1 = ProgressiveSidecarEngine.extract_l1_overview(SAMPLE_LONG_DOC, max_tokens=500)
    assert "# Distributed Memory Architecture ADR 042" in l1
    assert "## 1. Core Architectural Tenets" in l1
    assert "## 2. Interface Contracts" in l1
    assert "class DistributedMemoryNode:" in l1
    assert "def commit_transaction(self, tx_id: str) -> bool:" in l1

    # 3. Test three-tier bundle synthesis
    bundle = ProgressiveSidecarEngine.generate_bundle(
        doc_id="context://resources/adr_042.md",
        content=SAMPLE_LONG_DOC,
        title="ADR 042 Distributed Memory",
    )
    assert bundle.doc_id == "context://resources/adr_042.md"
    assert bundle.frontmatter.title == "ADR 042 Distributed Memory"
    assert len(bundle.frontmatter.digest_sha256) == 64
    assert bundle.frontmatter.l0_tokens_est < bundle.frontmatter.l2_tokens_est
    assert bundle.token_savings_pct > 60.0


def test_progressive_vfs_adapter_sidecar_write_and_tiered_read(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)
    adapter = ProgressiveContextVFSAdapter(vfs=vfs)

    doc_uri = "context://resources/adr_042.md"
    bundle = adapter.write_with_sidecars(
        uri=doc_uri,
        content=SAMPLE_LONG_DOC,
        title="ADR 042",
        metadata={"domain": "infrastructure"},
    )
    assert bundle.doc_id == doc_uri

    # 1. Verify companion sidecars exist in VFS directory listing
    children = vfs.ls("context://resources")
    names = [c.name for c in children]
    assert "adr_042.md" in names
    assert "adr_042.md.abstract.md" in names
    assert "adr_042.md.overview.md" in names

    # 2. Tier L0 Read (Abstract)
    read_l0 = adapter.read_tiered(doc_uri, tier=ContextTier.L0_ABSTRACT)
    assert read_l0.tier == ContextTier.L0_ABSTRACT
    assert read_l0.has_higher_detail is True
    assert "This document specifies" in read_l0.content
    assert read_l0.token_est < 120

    # 3. Tier L1 Read (Overview)
    read_l1 = adapter.read_tiered(doc_uri, tier=ContextTier.L1_OVERVIEW)
    assert read_l1.tier == ContextTier.L1_OVERVIEW
    assert read_l1.has_higher_detail is True
    assert "## 1. Core Architectural Tenets" in read_l1.content
    assert "class DistributedMemoryNode:" in read_l1.content

    # 4. Tier L2 Read (Full Detail)
    read_l2 = adapter.read_tiered(doc_uri, tier=ContextTier.L2_DETAIL)
    assert read_l2.tier == ContextTier.L2_DETAIL
    assert read_l2.has_higher_detail is False
    assert read_l2.content == SAMPLE_LONG_DOC

    vfs.close()


def test_progressive_vfs_adapter_fallback_generation(temp_db: Path) -> None:
    vfs = ContextVirtualFileSystem(db_path=temp_db)
    adapter = ProgressiveContextVFSAdapter(vfs=vfs)

    legacy_uri = "context://resources/legacy_spec.md"
    vfs.write(legacy_uri, SAMPLE_LONG_DOC)

    # Read L0 on document without existing sidecars generates dynamically
    fallback_l0 = adapter.read_tiered(legacy_uri, tier=ContextTier.L0_ABSTRACT)
    assert fallback_l0.tier == ContextTier.L0_ABSTRACT
    assert "This document specifies" in fallback_l0.content

    fallback_l1 = adapter.read_tiered(legacy_uri, tier=ContextTier.L1_OVERVIEW)
    assert fallback_l1.tier == ContextTier.L1_OVERVIEW
    assert "## 2. Interface Contracts" in fallback_l1.content

    vfs.close()
