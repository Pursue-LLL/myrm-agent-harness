"""[POS]: src/myrm_agent_harness/toolkits/memory/progressive_sidecar/adapter.py
[INPUT]: ContextVirtualFileSystem instances, canonical URIs, and context tier requests.
[OUTPUT]: ProgressiveContextVFSAdapter delivering seamless sidecar persistence and tiered disclosure.
"""

from myrm_agent_harness.toolkits.memory.cvfs import ContextVirtualFileSystem

from .engine import ProgressiveSidecarEngine
from .models import (
    ContextTier,
    ProgressiveContextBundle,
    ProgressiveReadResult,
)


class ProgressiveContextVFSAdapter:
    """Seamless adapter linking Context VFS with L0/L1/L2 progressive sidecar disclosure."""

    def __init__(self, vfs: ContextVirtualFileSystem) -> None:
        self.vfs = vfs

    @staticmethod
    def get_abstract_uri(uri: str) -> str:
        """Derive companion L0 abstract URI."""
        return f"{uri}.abstract.md"

    @staticmethod
    def get_overview_uri(uri: str) -> str:
        """Derive companion L1 overview URI."""
        return f"{uri}.overview.md"

    def write_with_sidecars(
        self,
        uri: str,
        content: str,
        title: str = "",
        metadata: dict[str, str] | None = None,
    ) -> ProgressiveContextBundle:
        """Persist primary L2 document and automatically generate and persist companion L0/L1 sidecars."""
        meta = metadata or {}
        # 1. Write primary L2 document
        self.vfs.write(uri=uri, content=content, metadata={**meta, "context_tier": ContextTier.L2_DETAIL.value})

        # 2. Synthesize three-tier bundle
        bundle = ProgressiveSidecarEngine.generate_bundle(doc_id=uri, content=content, title=title)

        # 3. Persist L0 abstract sidecar
        abstract_uri = self.get_abstract_uri(uri)
        self.vfs.write(
            uri=abstract_uri,
            content=bundle.l0_abstract,
            metadata={
                **meta,
                "sidecar_tier": ContextTier.L0_ABSTRACT.value,
                "parent_doc": uri,
                "digest_sha256": bundle.frontmatter.digest_sha256,
            },
        )

        # 4. Persist L1 overview sidecar
        overview_uri = self.get_overview_uri(uri)
        self.vfs.write(
            uri=overview_uri,
            content=bundle.l1_overview,
            metadata={
                **meta,
                "sidecar_tier": ContextTier.L1_OVERVIEW.value,
                "parent_doc": uri,
                "digest_sha256": bundle.frontmatter.digest_sha256,
            },
        )

        return bundle

    def read_tiered(
        self,
        uri: str,
        tier: ContextTier = ContextTier.L0_ABSTRACT,
    ) -> ProgressiveReadResult:
        """Read document at specified granularity tier with fallback generation."""
        if tier == ContextTier.L0_ABSTRACT:
            abstract_uri = self.get_abstract_uri(uri)
            try:
                res = self.vfs.read(abstract_uri)
                abstract_content = res.content
            except FileNotFoundError:
                raw_res = self.vfs.read(uri)
                abstract_content = ProgressiveSidecarEngine.extract_l0_abstract(raw_res.content)

            token_est = ProgressiveSidecarEngine.estimate_tokens(abstract_content)
            return ProgressiveReadResult(
                uri=uri,
                tier=ContextTier.L0_ABSTRACT,
                content=abstract_content,
                token_est=token_est,
                has_higher_detail=True,
            )

        if tier == ContextTier.L1_OVERVIEW:
            overview_uri = self.get_overview_uri(uri)
            try:
                res = self.vfs.read(overview_uri)
                overview_content = res.content
            except FileNotFoundError:
                raw_res = self.vfs.read(uri)
                overview_content = ProgressiveSidecarEngine.extract_l1_overview(raw_res.content)

            token_est = ProgressiveSidecarEngine.estimate_tokens(overview_content)
            return ProgressiveReadResult(
                uri=uri,
                tier=ContextTier.L1_OVERVIEW,
                content=overview_content,
                token_est=token_est,
                has_higher_detail=True,
            )

        # L2 Full verbatim detail
        raw_res = self.vfs.read(uri)
        token_est = ProgressiveSidecarEngine.estimate_tokens(raw_res.content)
        return ProgressiveReadResult(
            uri=uri,
            tier=ContextTier.L2_DETAIL,
            content=raw_res.content,
            token_est=token_est,
            has_higher_detail=False,
        )
