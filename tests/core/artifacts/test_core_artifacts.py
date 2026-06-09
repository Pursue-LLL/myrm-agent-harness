"""Tests for core.artifacts — framework-agnostic artifact constants and utilities."""

from myrm_agent_harness.core.artifacts import (
    ACTIVE_CONTENT_MIME_TYPES,
    EXTENSION_TO_ARTIFACT_TYPE,
    EXTENSION_TO_LANGUAGE,
    ArtifactType,
    get_all_mappings,
    infer_artifact_type_from_extension,
    infer_artifact_type_from_mime,
    infer_language_from_extension,
    is_active_content,
    is_text_content,
)


class TestArtifactType:
    def test_is_str_enum(self) -> None:
        assert isinstance(ArtifactType.CODE, str)
        assert ArtifactType.CODE == "code"

    def test_key_types_exist(self) -> None:
        required = {"CODE", "DOCUMENT", "HTML", "IMAGE", "SVG", "PDF", "BINARY"}
        actual = {t.name for t in ArtifactType}
        assert required.issubset(actual)


class TestExtensionMappings:
    def test_python_extension(self) -> None:
        assert EXTENSION_TO_LANGUAGE[".py"] == "python"

    def test_typescript_extension(self) -> None:
        assert EXTENSION_TO_LANGUAGE[".ts"] == "typescript"

    def test_code_artifact_type(self) -> None:
        assert EXTENSION_TO_ARTIFACT_TYPE[".py"] == ArtifactType.CODE

    def test_html_artifact_type(self) -> None:
        assert EXTENSION_TO_ARTIFACT_TYPE[".html"] == ArtifactType.HTML


class TestInferFunctions:
    def test_infer_language_python(self) -> None:
        assert infer_language_from_extension("main.py") == "python"

    def test_infer_language_unknown(self) -> None:
        assert infer_language_from_extension("file.xyz123") is None

    def test_infer_type_from_extension_known(self) -> None:
        assert infer_artifact_type_from_extension("app.ts") == ArtifactType.CODE

    def test_infer_type_from_extension_document(self) -> None:
        result = infer_artifact_type_from_extension("readme.txt")
        assert result in (ArtifactType.DOCUMENT, ArtifactType.BINARY, ArtifactType.CODE)

    def test_infer_type_from_extension_extra_document(self) -> None:
        assert infer_artifact_type_from_extension("server.log") == ArtifactType.DOCUMENT

    def test_infer_type_from_extension_spreadsheet(self) -> None:
        assert infer_artifact_type_from_extension("data.csv") == ArtifactType.SPREADSHEET
        assert infer_artifact_type_from_extension("data.tsv") == ArtifactType.SPREADSHEET
        assert infer_artifact_type_from_extension("data.xlsx") == ArtifactType.SPREADSHEET

    def test_infer_type_from_extension_extra_binary(self) -> None:
        assert infer_artifact_type_from_extension("archive.zip") == ArtifactType.BINARY
        assert infer_artifact_type_from_extension("video.mp4") == ArtifactType.BINARY
        assert infer_artifact_type_from_extension("app.exe") == ArtifactType.BINARY

    def test_infer_type_from_extension_unknown(self) -> None:
        assert infer_artifact_type_from_extension("file.zzz99") == ArtifactType.BINARY

    def test_infer_type_from_mime_html(self) -> None:
        assert infer_artifact_type_from_mime("text/html") == ArtifactType.HTML

    def test_infer_type_from_mime_unknown(self) -> None:
        assert infer_artifact_type_from_mime("application/x-unknown") == ArtifactType.BINARY


class TestSecurityFunctions:
    def test_active_content_html(self) -> None:
        assert is_active_content("text/html") is True

    def test_active_content_svg(self) -> None:
        assert is_active_content("image/svg+xml") is True

    def test_non_active_content(self) -> None:
        assert is_active_content("text/plain") is False

    def test_active_content_mime_types_frozenset(self) -> None:
        assert isinstance(ACTIVE_CONTENT_MIME_TYPES, frozenset)

    def test_is_text_content_text(self) -> None:
        assert is_text_content(b"Hello, world!") is True

    def test_is_text_content_binary(self) -> None:
        assert is_text_content(b"\x00\x01\x02\x03") is False


class TestGetAllMappings:
    def test_returns_typed_dict(self) -> None:
        m = get_all_mappings()
        assert "artifactTypes" in m
        assert "extensionToLanguage" in m
        assert "extensionToArtifactType" in m
        assert "mimeToArtifactType" in m

    def test_artifact_types_list(self) -> None:
        m = get_all_mappings()
        assert "code" in m["artifactTypes"]
        assert "document" in m["artifactTypes"]

    def test_extension_mappings_present(self) -> None:
        m = get_all_mappings()
        assert ".py" in m["extensionToLanguage"]
        assert ".py" in m["extensionToArtifactType"]


class TestReExportTypeIdentity:
    def test_artifact_type_identity(self) -> None:
        from myrm_agent_harness.agent.artifacts.constants import (
            ArtifactType as AgentArtifactType,
        )

        assert ArtifactType is AgentArtifactType

    def test_isinstance_cross_module(self) -> None:
        from myrm_agent_harness.agent.artifacts.constants import (
            ArtifactType as AgentArtifactType,
        )

        assert isinstance(ArtifactType.CODE, AgentArtifactType)
