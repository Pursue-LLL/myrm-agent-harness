"""Tests for ContentVault Protocol — cross-layer DI for browser content persistence."""

from __future__ import annotations

from myrm_agent_harness.toolkits.browser.session.browser_session import ContentVault


class TestContentVaultProtocol:
    def test_conforming_class_passes_isinstance(self) -> None:
        class FakeVault:
            def put(self, content: str | bytes, filename: str, content_type: str | None = None, description: str = "") -> str:
                return "vault://fake-id"

        assert isinstance(FakeVault(), ContentVault)

    def test_non_conforming_class_rejected(self) -> None:
        class NotAVault:
            pass

        assert not isinstance(NotAVault(), ContentVault)

    def test_artifact_vault_satisfies_protocol(self) -> None:
        import tempfile

        from myrm_agent_harness.agent.artifacts.vault import ArtifactVault

        vault = ArtifactVault(tempfile.mkdtemp())
        assert isinstance(vault, ContentVault)

    def test_put_returns_uri(self) -> None:
        class InMemoryVault:
            def put(self, content: str | bytes, filename: str, content_type: str | None = None, description: str = "") -> str:
                return f"vault://{filename}"

        vault = InMemoryVault()
        uri = vault.put("hello", "test.txt", "text/plain", "test content")
        assert uri == "vault://test.txt"
