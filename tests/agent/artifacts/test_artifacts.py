"""Unit tests for artifact system."""

import asyncio

from myrm_agent_harness.agent.artifacts import (
    EXTENSION_TO_ARTIFACT_TYPE,
    EXTENSION_TO_LANGUAGE,
    ArtifactInfo,
    ArtifactRegistry,
    ArtifactType,
    GeneratedFile,
    InlineArtifactEvent,
    InlineArtifactQueue,
    get_inline_artifact_queue,
    infer_artifact_type,
    infer_artifact_type_from_extension,
    infer_artifact_type_from_mime,
    infer_language,
    infer_language_from_extension,
    is_active_content,
    is_text_content,
    push_inline_artifact,
    should_filter_skill_resource,
    should_ignore_artifact,
)
from myrm_agent_harness.agent.artifacts.constants import ACTIVE_CONTENT_MIME_TYPES, get_all_mappings
from myrm_agent_harness.agent.artifacts.context import ArtifactContext, ArtifactContextManager, get_artifact_context
from myrm_agent_harness.agent.artifacts.file_id_registry import FileIdRegistry, is_file_id, resolve_file_ids_in_text
from myrm_agent_harness.agent.artifacts.ui_artifact import (
    UIAction,
    UIArtifact,
    UIComponent,
    UIComponentType,
    UIDataUpdate,
    create_button,
    create_card,
    create_select,
    create_table,
    create_tabs,
    create_text,
    create_text_field,
)
from myrm_agent_harness.agent.artifacts.ui_registry import UIRegistry, get_ui_registry


class TestArtifactTypes:
    """Tests for artifact type inference."""

    def test_infer_language_python(self):
        """Test Python language inference."""
        assert infer_language("app.py") == "python"
        assert infer_language("script.pyw") == "python"

    def test_infer_language_javascript(self):
        """Test JavaScript language inference."""
        assert infer_language("app.js") == "javascript"
        assert infer_language("Component.jsx") == "jsx"

    def test_infer_language_unknown(self):
        """Test unknown file extension."""
        assert infer_language("file.xyz") is None
        assert infer_language("README") is None

    def test_infer_artifact_type_code(self):
        """Test code artifact type inference."""
        assert infer_artifact_type("app.py") == ArtifactType.CODE
        assert infer_artifact_type("styles.css") == ArtifactType.CODE
        assert infer_artifact_type("config.json") == ArtifactType.CODE

    def test_infer_artifact_type_document(self):
        """Test document artifact type inference."""
        assert infer_artifact_type("README.md") == ArtifactType.DOCUMENT
        assert infer_artifact_type("notes.txt") == ArtifactType.DOCUMENT
        assert infer_artifact_type("data.csv") == ArtifactType.SPREADSHEET

    def test_infer_artifact_type_image(self):
        """Test image artifact type inference."""
        assert infer_artifact_type("chart.png") == ArtifactType.IMAGE
        assert infer_artifact_type("photo.jpg") == ArtifactType.IMAGE
        assert infer_artifact_type("icon.gif") == ArtifactType.IMAGE

    def test_infer_artifact_type_html(self):
        """Test HTML artifact type inference."""
        assert infer_artifact_type("index.html") == ArtifactType.HTML
        assert infer_artifact_type("page.htm") == ArtifactType.HTML

    def test_infer_artifact_type_svg(self):
        """Test SVG artifact type inference."""
        assert infer_artifact_type("diagram.svg") == ArtifactType.SVG

    def test_infer_artifact_type_pdf(self):
        """Test PDF artifact type inference."""
        assert infer_artifact_type("document.pdf") == ArtifactType.PDF

    def test_infer_artifact_type_binary(self):
        """Test binary artifact type inference (default)."""
        assert infer_artifact_type("archive.zip") == ArtifactType.BINARY
        assert infer_artifact_type("app.exe") == ArtifactType.BINARY
        assert infer_artifact_type("unknown.xyz") == ArtifactType.BINARY

    def test_extension_mappings_complete(self):
        """Test that extension mappings are comprehensive."""
        assert ".py" in EXTENSION_TO_LANGUAGE
        assert ".js" in EXTENSION_TO_LANGUAGE
        assert ".ts" in EXTENSION_TO_LANGUAGE
        assert ".go" in EXTENSION_TO_LANGUAGE

        assert ".py" in EXTENSION_TO_ARTIFACT_TYPE
        assert ".png" in EXTENSION_TO_ARTIFACT_TYPE
        assert ".pdf" in EXTENSION_TO_ARTIFACT_TYPE


class TestInferFunctions:
    """Tests for SSoT inference functions in constants.py."""

    def test_infer_artifact_type_from_extension_primary(self):
        """Primary mapping: extensions in EXTENSION_TO_ARTIFACT_TYPE."""
        assert infer_artifact_type_from_extension("app.py") == ArtifactType.CODE
        assert infer_artifact_type_from_extension("index.html") == ArtifactType.HTML
        assert infer_artifact_type_from_extension("diagram.svg") == ArtifactType.SVG
        assert infer_artifact_type_from_extension("chart.png") == ArtifactType.IMAGE
        assert infer_artifact_type_from_extension("doc.pdf") == ArtifactType.PDF
        assert infer_artifact_type_from_extension("flow.mermaid") == ArtifactType.MERMAID

    def test_infer_artifact_type_from_extension_extra_document(self):
        """Fallback: extra document extensions (.log)."""
        assert infer_artifact_type_from_extension("server.log") == ArtifactType.DOCUMENT

    def test_infer_artifact_type_from_extension_spreadsheet(self):
        """Spreadsheet extensions (.csv, .tsv, .xlsx, .xls)."""
        assert infer_artifact_type_from_extension("data.csv") == ArtifactType.SPREADSHEET
        assert infer_artifact_type_from_extension("data.tsv") == ArtifactType.SPREADSHEET
        assert infer_artifact_type_from_extension("data.xlsx") == ArtifactType.SPREADSHEET
        assert infer_artifact_type_from_extension("data.xls") == ArtifactType.SPREADSHEET

    def test_infer_artifact_type_from_extension_extra_binary(self):
        """Fallback: extra binary extensions (archives, office, media)."""
        assert infer_artifact_type_from_extension("archive.zip") == ArtifactType.BINARY
        assert infer_artifact_type_from_extension("doc.docx") == ArtifactType.BINARY
        assert infer_artifact_type_from_extension("video.mp4") == ArtifactType.BINARY
        assert infer_artifact_type_from_extension("app.exe") == ArtifactType.BINARY

    def test_infer_artifact_type_from_extension_unknown(self):
        """Default: unknown extensions fall back to BINARY."""
        assert infer_artifact_type_from_extension("file.xyz") == ArtifactType.BINARY
        assert infer_artifact_type_from_extension("noext") == ArtifactType.BINARY

    def test_infer_artifact_type_from_mime(self):
        """MIME type inference."""
        assert infer_artifact_type_from_mime("text/x-python") == ArtifactType.CODE
        assert infer_artifact_type_from_mime("text/html") == ArtifactType.HTML
        assert infer_artifact_type_from_mime("image/png") == ArtifactType.IMAGE
        assert infer_artifact_type_from_mime("image/svg+xml") == ArtifactType.SVG
        assert infer_artifact_type_from_mime("application/pdf") == ArtifactType.PDF
        assert infer_artifact_type_from_mime("application/octet-stream") == ArtifactType.BINARY
        assert infer_artifact_type_from_mime("unknown/type") == ArtifactType.BINARY

    def test_infer_language_from_extension(self):
        """Language inference from SSoT function."""
        assert infer_language_from_extension("app.py") == "python"
        assert infer_language_from_extension("index.ts") == "typescript"
        assert infer_language_from_extension("style.css") == "css"
        assert infer_language_from_extension("unknown.xyz") is None

    def test_alias_consistency(self):
        """Alias functions in types.py produce same results as SSoT functions."""
        test_files = ["app.py", "index.html", "data.csv", "archive.zip", "unknown.xyz"]
        for f in test_files:
            assert infer_artifact_type(f) == infer_artifact_type_from_extension(f)
            assert infer_language(f) == infer_language_from_extension(f)


class TestFileFilters:
    """Tests for file filtering rules."""

    def test_ignore_ds_store(self):
        """Test .DS_Store is ignored."""
        assert should_ignore_artifact(".DS_Store") is True

    def test_ignore_pyc(self):
        """Test .pyc files are ignored."""
        assert should_ignore_artifact("test.pyc") is True
        assert should_ignore_artifact("module.pyc") is True

    def test_ignore_pycache(self):
        """Test __pycache__ is ignored."""
        assert should_ignore_artifact("__pycache__") is True

    def test_ignore_metadata(self):
        """Test metadata files are ignored."""
        assert should_ignore_artifact("_metadata.json") is True

    def test_ignore_wrapper_scripts(self):
        """Test wrapper scripts are ignored."""
        assert should_ignore_artifact("run.py") is True
        assert should_ignore_artifact("user_code.py") is True

    def test_not_ignore_regular_files(self):
        """Test regular files are not ignored."""
        assert should_ignore_artifact("output.txt") is False
        assert should_ignore_artifact("chart.png") is False
        assert should_ignore_artifact("app.py") is False

    def test_exact_match_no_substring(self):
        """Filenames containing ignored patterns as substrings should NOT be filtered."""
        assert should_ignore_artifact("autorun.py") is False
        assert should_ignore_artifact("my_metadata.json") is False
        assert should_ignore_artifact("user_code.py.bak") is False

    def test_filter_skill_resources(self):
        """Test skill resource files are filtered."""
        assert should_filter_skill_resource(".claude/skills/ui-ux/data/colors.csv") is True
        assert should_filter_skill_resource(".claude/skills/pptx/scripts/main.py") is True
        assert should_filter_skill_resource(".claude/skills/test/SKILL.md") is True

    def test_not_filter_user_files(self):
        """Test user files are not filtered."""
        assert should_filter_skill_resource("output.html") is False
        assert should_filter_skill_resource("my-skill/output.pdf") is False
        assert should_filter_skill_resource("workspace/data.csv") is False


class TestArtifactInfo:
    """Tests for ArtifactInfo data model."""

    def test_create_artifact_info(self):
        """Test creating ArtifactInfo."""
        artifact = ArtifactInfo(
            id="file123",
            filename="output.py",
            type=ArtifactType.CODE,
            content_type="text/x-python",
            size=1024,
            preview_url="/api/files/file123",
            download_url="/api/files/file123/download",
            language="python",
            created_at="2024-01-01T00:00:00Z",
        )

        assert artifact.id == "file123"
        assert artifact.filename == "output.py"
        assert artifact.type == ArtifactType.CODE
        assert artifact.language == "python"

    def test_artifact_info_to_dict(self):
        """Test converting ArtifactInfo to dictionary."""
        artifact = ArtifactInfo(
            id="file123",
            filename="output.py",
            type=ArtifactType.CODE,
            content_type="text/x-python",
            size=1024,
            preview_url="/api/files/file123",
            download_url="/api/files/file123/download",
        )

        data = artifact.to_dict()

        assert isinstance(data, dict)
        assert data["id"] == "file123"
        assert data["type"] == "code"

    def test_artifact_info_file_path_none_excluded(self):
        """Test that file_path=None is excluded from to_dict() output."""
        artifact = ArtifactInfo(
            id="file123",
            filename="output.py",
            type=ArtifactType.CODE,
            content_type="text/x-python",
            size=1024,
            preview_url="/api/files/file123",
            download_url="/api/files/file123/download",
        )

        data = artifact.to_dict()
        assert "file_path" not in data

    def test_artifact_info_file_path_included(self):
        """Test that file_path with value is included in to_dict() output."""
        artifact = ArtifactInfo(
            id="file123",
            filename="output.py",
            type=ArtifactType.CODE,
            content_type="text/x-python",
            size=1024,
            preview_url="/api/files/file123",
            download_url="/api/files/file123/download",
            file_path="/workspace/output.py",
        )

        data = artifact.to_dict()
        assert "file_path" in data
        assert data["file_path"] == "/workspace/output.py"

    def test_artifact_info_file_path_default_none(self):
        """Test that file_path defaults to None."""
        artifact = ArtifactInfo(
            id="f1",
            filename="x.txt",
            type=ArtifactType.DOCUMENT,
            content_type="text/plain",
            size=10,
            preview_url="/api/files/f1",
            download_url="/api/files/f1/download",
        )
        assert artifact.file_path is None


class TestGeneratedFile:
    """Tests for GeneratedFile data model."""

    def test_create_generated_file_local(self):
        """Test creating GeneratedFile for local mode."""
        file = GeneratedFile(path="/tmp/workspace/output.txt")

        assert file.path == "/tmp/workspace/output.txt"
        assert file.container_id is None

    def test_create_generated_file_docker(self):
        """Test creating GeneratedFile for Docker mode."""
        file = GeneratedFile(path="/workspace/output.txt", container_id="container123")

        assert file.path == "/workspace/output.txt"
        assert file.container_id == "container123"


class TestArtifactRegistry:
    """Tests for ArtifactRegistry."""

    def test_create_empty_registry(self):
        """Test creating empty registry."""
        registry = ArtifactRegistry()

        assert len(registry.get_all_files()) == 0

    def test_add_files(self):
        """Test adding files to registry."""
        registry = ArtifactRegistry()

        registry.add_files(["output.txt", "chart.png"])

        assert len(registry) == 2
        files = registry.get_all_files()
        assert files[0].path == "output.txt"
        assert files[1].path == "chart.png"

    def test_add_files_with_container_id(self):
        """Test adding files with container ID."""
        registry = ArtifactRegistry()

        registry.add_files(["/workspace/output.txt"], container_id="container123")

        files = registry.get_all_files()
        assert len(files) == 1
        assert files[0].container_id == "container123"

    def test_automatic_deduplication(self):
        """Test automatic file deduplication."""
        registry = ArtifactRegistry()

        # Add same file multiple times
        registry.add_files(["output.txt"])
        registry.add_files(["output.txt"])
        registry.add_files(["output.txt"])

        # Should only have one entry
        assert len(registry) == 1

    def test_automatic_filtering_system_files(self):
        """Test automatic filtering of system files."""
        registry = ArtifactRegistry()

        registry.add_files(
            [
                "output.txt",
                ".DS_Store",  # Should be filtered
                "chart.png",
                "test.pyc",  # Should be filtered
            ]
        )

        # Should only have 2 files (output.txt, chart.png)
        assert len(registry) == 2

    def test_automatic_filtering_skill_resources(self):
        """Test automatic filtering of skill resources."""
        registry = ArtifactRegistry()

        registry.add_files(
            [
                "output.txt",
                ".claude/skills/ui-ux/data/colors.csv",  # Should be filtered
                "chart.png",
                ".claude/skills/pptx/SKILL.md",  # Should be filtered
            ]
        )

        # Should only have 2 files (output.txt, chart.png)
        assert len(registry) == 2

    def test_clear_registry(self):
        """Test clearing registry."""
        registry = ArtifactRegistry()

        registry.add_files(["output.txt", "chart.png"])
        assert len(registry) == 2

        registry.clear()
        assert len(registry) == 0

    def test_get_all_files_returns_copy(self):
        """Test that get_all_files returns a copy."""
        registry = ArtifactRegistry()
        registry.add_files(["output.txt"])

        files1 = registry.get_all_files()
        files2 = registry.get_all_files()

        # Should be different list instances
        assert files1 is not files2
        # But with same content
        assert files1[0].path == files2[0].path


class TestActiveContentSecurity:
    """Tests for is_active_content() XSS protection."""

    def test_html_is_active(self):
        assert is_active_content("text/html") is True

    def test_xhtml_is_active(self):
        assert is_active_content("application/xhtml+xml") is True

    def test_svg_is_active(self):
        assert is_active_content("image/svg+xml") is True

    def test_plain_text_not_active(self):
        assert is_active_content("text/plain") is False

    def test_json_not_active(self):
        assert is_active_content("application/json") is False

    def test_image_png_not_active(self):
        assert is_active_content("image/png") is False

    def test_empty_string_not_active(self):
        assert is_active_content("") is False

    def test_frozenset_immutable(self):
        assert isinstance(ACTIVE_CONTENT_MIME_TYPES, frozenset)
        assert len(ACTIVE_CONTENT_MIME_TYPES) == 3


class TestTextContentDetection:
    """Tests for is_text_content() null byte detection."""

    def test_plain_text(self):
        assert is_text_content(b"Hello, World!") is True

    def test_python_code(self):
        assert is_text_content(b"def foo():\n    return 42\n") is True

    def test_empty_bytes(self):
        assert is_text_content(b"") is True

    def test_png_header(self):
        assert is_text_content(b"\x89PNG\r\n\x1a\n\x00") is False

    def test_binary_with_null_bytes(self):
        assert is_text_content(b"some\x00binary\x00data") is False

    def test_sample_size_limit(self):
        data = b"a" * 10000 + b"\x00"
        assert is_text_content(data, sample_size=5000) is True
        assert is_text_content(data, sample_size=20000) is False

    def test_utf8_text(self):
        assert is_text_content("你好世界".encode()) is True


class TestGetAllMappings:
    """Tests for get_all_mappings() API response format."""

    def test_returns_typed_dict(self):
        mappings = get_all_mappings()
        assert "artifactTypes" in mappings
        assert "extensionToLanguage" in mappings
        assert "extensionToArtifactType" in mappings
        assert "mimeToArtifactType" in mappings

    def test_artifact_types_list(self):
        mappings = get_all_mappings()
        types = mappings["artifactTypes"]
        assert "code" in types
        assert "html" in types
        assert "image" in types
        assert "pdf" in types

    def test_extension_values_are_strings(self):
        mappings = get_all_mappings()
        for ext, lang in mappings["extensionToLanguage"].items():
            assert isinstance(ext, str)
            assert isinstance(lang, str)
        for ext, atype in mappings["extensionToArtifactType"].items():
            assert isinstance(ext, str)
            assert isinstance(atype, str)


class TestArtifactContextManager:
    """Tests for ArtifactContextManager lifecycle and ContextVar isolation."""

    def test_sync_context_lifecycle(self):
        assert get_artifact_context() is None

        with ArtifactContextManager(message_id="msg_1") as ctx:
            assert ctx is not None
            assert isinstance(ctx, ArtifactContext)
            assert ctx.message_id == "msg_1"
            assert get_artifact_context() is ctx

        assert get_artifact_context() is None

    def test_async_context_lifecycle(self):
        async def _test():
            assert get_artifact_context() is None

            async with ArtifactContextManager(message_id="async_msg") as ctx:
                assert ctx is not None
                assert ctx.message_id == "async_msg"
                assert get_artifact_context() is ctx

            assert get_artifact_context() is None

        asyncio.run(_test())

    def test_registries_initialized(self):
        with ArtifactContextManager() as ctx:
            assert ctx.artifact_registry is not None
            assert ctx.ui_registry is not None
            assert ctx.realtime_content_queue is not None
            assert ctx.inline_artifact_queue is not None
            assert ctx.file_id_registry is not None

    def test_cleanup_on_exception(self):
        try:
            with ArtifactContextManager():
                raise ValueError("test error")
        except ValueError:
            pass

        assert get_artifact_context() is None

    def test_nested_contexts_independent(self):
        with ArtifactContextManager(message_id="outer") as outer_ctx:
            outer_ctx.artifact_registry.add_files(["outer.txt"])

            with ArtifactContextManager(message_id="inner") as inner_ctx:
                assert inner_ctx.message_id == "inner"
                assert get_artifact_context() is inner_ctx
                assert len(inner_ctx.artifact_registry.get_all_files()) == 0

            assert get_artifact_context() is outer_ctx
            assert len(outer_ctx.artifact_registry.get_all_files()) == 1


class TestFileIdRegistry:
    """Tests for FileIdRegistry register/resolve/dedup."""

    def test_register_returns_sequential_ids(self):
        registry = FileIdRegistry()
        id1 = registry.register("/workspace/a.txt")
        id2 = registry.register("/workspace/b.txt")

        assert id1 == "@file_001"
        assert id2 == "@file_002"

    def test_register_dedup(self):
        registry = FileIdRegistry()
        id1 = registry.register("/workspace/a.txt")
        id2 = registry.register("/workspace/a.txt")

        assert id1 == id2
        assert len(registry.id_to_path) == 1

    def test_resolve_existing(self):
        registry = FileIdRegistry()
        registry.register("/workspace/test.py")

        path = registry.resolve("@file_001")
        assert path == "/workspace/test.py"

    def test_resolve_nonexistent(self):
        registry = FileIdRegistry()
        assert registry.resolve("@file_999") is None

    def test_get_all_mappings(self):
        registry = FileIdRegistry()
        registry.register("/workspace/a.txt")
        registry.register("/workspace/b.txt")

        mappings = registry.get_all_mappings()
        assert len(mappings) == 2
        assert mappings["@file_001"] == "/workspace/a.txt"

    def test_is_file_id(self):
        assert is_file_id("@file_001") is True
        assert is_file_id("@file_100") is True
        assert is_file_id("/workspace/test.py") is False
        assert is_file_id("file_001") is False

    def test_resolve_file_ids_in_text_within_context(self):
        with ArtifactContextManager():
            ctx = get_artifact_context()
            assert ctx is not None
            ctx.file_id_registry.register("/workspace/data.json")

            result = resolve_file_ids_in_text("cat @file_001 | jq '.data'")
            assert result == "cat /workspace/data.json | jq '.data'"

    def test_resolve_file_ids_preserves_unknown(self):
        with ArtifactContextManager():
            result = resolve_file_ids_in_text("cat @file_999")
            assert "@file_999" in result

    def test_resolve_file_ids_no_context(self):
        result = resolve_file_ids_in_text("cat @file_001")
        assert result == "cat @file_001"


class TestUIRegistry:
    """Tests for UIRegistry add/pop/clear."""

    def test_add_ui_artifact(self):
        registry = UIRegistry()
        ui = UIArtifact(title="Test", components=[], root_ids=[], data={})
        registry.add_ui(ui)

        assert len(registry.ui_artifacts) == 1

    def test_add_data_update(self):
        registry = UIRegistry()
        update = UIDataUpdate(surface_id="surface_1", updates={"counter": 42})
        registry.add_data_update(update)

        assert len(registry.data_updates) == 1

    def test_pop_pending_events_returns_and_clears(self):
        registry = UIRegistry()
        ui = UIArtifact(title="T", components=[], root_ids=[], data={})
        update = UIDataUpdate(surface_id="s1", updates={"k": "v"})

        registry.add_ui(ui)
        registry.add_data_update(update)

        events = registry.pop_pending_events()
        assert len(events) == 2

        # After pop, should be empty
        assert not registry.has_pending_events()
        assert registry.pop_pending_events() == []

    def test_has_pending_events(self):
        registry = UIRegistry()
        assert registry.has_pending_events() is False

        registry.add_ui(UIArtifact(title="T", components=[], root_ids=[], data={}))
        assert registry.has_pending_events() is True

    def test_clear(self):
        registry = UIRegistry()
        registry.add_ui(UIArtifact(title="T", components=[], root_ids=[], data={}))
        registry.add_data_update(UIDataUpdate(surface_id="s1", updates={"k": "v"}))

        registry.clear()
        assert not registry.has_pending_events()

    def test_get_ui_registry_within_context(self):
        with ArtifactContextManager():
            reg = get_ui_registry()
            assert reg is not None
            assert isinstance(reg, UIRegistry)

    def test_get_ui_registry_outside_context(self):
        assert get_ui_registry() is None

    def test_add_ui_with_message_id_stashes_for_cross_task_collect(self):
        from myrm_agent_harness.agent.artifacts.ui_registry import pop_pending_ui_events_for_message

        with ArtifactContextManager(message_id="msg_cross_task"):
            registry = get_ui_registry()
            assert registry is not None
            ui = UIArtifact(title="Stashed", components=[], root_ids=[], data={})
            registry.add_ui(ui)
            assert registry.ui_artifacts == []
            assert not registry.has_pending_events()

        stashed = pop_pending_ui_events_for_message("msg_cross_task")
        assert len(stashed) == 1
        assert stashed[0].title == "Stashed"
        assert pop_pending_ui_events_for_message("msg_cross_task") == []

    def test_register_ui_artifact_without_artifact_context_uses_bound_message_id(self):
        from myrm_agent_harness.agent.artifacts.ui_registry import (
            bind_run_message_id,
            pop_pending_ui_events_for_message,
            pop_run_message_id,
            register_ui_artifact,
        )

        bind_run_message_id("chat_test", "msg_bound_turn")
        ui = UIArtifact(title="Bound", components=[], root_ids=[], data={})
        assert register_ui_artifact(ui) is True
        stashed = pop_pending_ui_events_for_message("msg_bound_turn")
        assert len(stashed) == 1
        assert stashed[0].title == "Bound"
        pop_run_message_id("chat_test")


class TestUIComponentType:
    """Tests for UIComponentType enum completeness."""

    def test_all_component_types_defined(self):
        expected = {
            "text", "button", "button_group",
            "text_field", "textarea", "select", "date_picker", "time_picker",
            "slider", "checkbox", "radio", "switch",
            "container", "card", "divider", "grid", "tabs",
            "table", "list", "image", "chart", "progress", "badge",
        }
        actual = {t.value for t in UIComponentType}
        assert actual == expected

    def test_tabs_in_enum(self):
        assert UIComponentType.TABS.value == "tabs"
        assert UIComponentType("tabs") == UIComponentType.TABS


class TestUIComponent:
    """Tests for UIComponent Pydantic model."""

    def test_create_component_minimal(self):
        comp = UIComponent(type=UIComponentType.TEXT)
        assert comp.type == UIComponentType.TEXT
        assert len(comp.id) == 8
        assert comp.props == {}
        assert comp.children == []
        assert comp.bindings == {}
        assert comp.events == {}

    def test_create_component_with_all_fields(self):
        comp = UIComponent(
            id="my_comp",
            type=UIComponentType.TABS,
            props={"tabs": [{"label": "Tab A"}]},
            children=["child_1", "child_2"],
            bindings={"value": "$.state"},
            events={"onChange": "action_1"},
        )
        assert comp.id == "my_comp"
        assert comp.type == UIComponentType.TABS
        assert comp.props["tabs"] == [{"label": "Tab A"}]
        assert comp.children == ["child_1", "child_2"]

    def test_component_serialization(self):
        comp = UIComponent(id="c1", type=UIComponentType.CARD, props={"title": "Test"})
        data = comp.model_dump()
        assert data["id"] == "c1"
        assert data["type"] == "card"
        assert data["props"]["title"] == "Test"


class TestUIArtifactModel:
    """Tests for UIArtifact Pydantic model."""

    def test_create_full_artifact(self):
        comp = UIComponent(id="tab", type=UIComponentType.TABS, props={"tabs": [{"label": "A"}]}, children=["c1"])
        child = UIComponent(id="c1", type=UIComponentType.TEXT, props={"text": "Content"})
        action = UIAction(id="act1", type="submit", label="Submit")

        artifact = UIArtifact(
            title="Test UI",
            components=[comp, child],
            root_ids=["tab"],
            data={"form": {}},
            actions=[action],
        )
        assert artifact.title == "Test UI"
        assert len(artifact.components) == 2
        assert artifact.root_ids == ["tab"]
        assert artifact.data == {"form": {}}
        assert len(artifact.actions) == 1

    def test_artifact_to_dict(self):
        artifact = UIArtifact(
            title="T",
            components=[UIComponent(id="t1", type=UIComponentType.TEXT, props={"text": "hi"})],
            root_ids=["t1"],
            data={},
        )
        d = artifact.to_dict()
        assert isinstance(d, dict)
        assert d["title"] == "T"
        assert len(d["components"]) == 1
        assert d["components"][0]["type"] == "text"


class TestUIComponentFactories:
    """Tests for convenience factory functions."""

    def test_create_text(self):
        comp = create_text("Hello", component_id="t1", variant="heading")
        assert comp.id == "t1"
        assert comp.type == UIComponentType.TEXT
        assert comp.props["text"] == "Hello"
        assert comp.props["variant"] == "heading"

    def test_create_text_auto_id(self):
        comp = create_text("Hi")
        assert len(comp.id) == 8

    def test_create_button(self):
        comp = create_button("Click me", "action_submit", component_id="btn1", variant="primary")
        assert comp.id == "btn1"
        assert comp.type == UIComponentType.BUTTON
        assert comp.props["label"] == "Click me"
        assert comp.props["variant"] == "primary"
        assert comp.events["onClick"] == "action_submit"

    def test_create_text_field(self):
        comp = create_text_field("Name", "$.form.name", component_id="f1", placeholder="Enter name")
        assert comp.id == "f1"
        assert comp.type == UIComponentType.TEXT_FIELD
        assert comp.props["label"] == "Name"
        assert comp.props["placeholder"] == "Enter name"
        assert comp.bindings["value"] == "$.form.name"

    def test_create_select(self):
        comp = create_select("Color", ["red", "blue"], "$.form.color", component_id="s1")
        assert comp.id == "s1"
        assert comp.type == UIComponentType.SELECT
        assert comp.props["options"] == ["red", "blue"]
        assert comp.bindings["value"] == "$.form.color"

    def test_create_card(self):
        comp = create_card("My Card", ["c1", "c2"], component_id="card1")
        assert comp.id == "card1"
        assert comp.type == UIComponentType.CARD
        assert comp.props["title"] == "My Card"
        assert comp.children == ["c1", "c2"]

    def test_create_tabs(self):
        comp = create_tabs(
            tabs=[{"label": "Tab A"}, {"label": "Tab B"}],
            children=["panel_a", "panel_b"],
            component_id="tabs1",
        )
        assert comp.id == "tabs1"
        assert comp.type == UIComponentType.TABS
        assert comp.props["tabs"] == [{"label": "Tab A"}, {"label": "Tab B"}]
        assert comp.children == ["panel_a", "panel_b"]

    def test_create_tabs_with_extra_props(self):
        comp = create_tabs(
            tabs=[{"label": "X"}],
            children=["x"],
            defaultIndex=1,
        )
        assert comp.props["defaultIndex"] == 1
        assert comp.props["tabs"] == [{"label": "X"}]

    def test_create_tabs_auto_id(self):
        comp = create_tabs(tabs=[{"label": "A"}], children=["a"])
        assert len(comp.id) == 8

    def test_create_table(self):
        comp = create_table(
            columns=[{"key": "name", "title": "Name"}],
            data_path="$.items",
            component_id="tbl1",
        )
        assert comp.id == "tbl1"
        assert comp.type == UIComponentType.TABLE
        assert comp.props["columns"] == [{"key": "name", "title": "Name"}]
        assert comp.bindings["data"] == "$.items"

    def test_tabs_in_full_artifact(self):
        """End-to-end: create_tabs in a full UIArtifact."""
        tab_comp = create_tabs(
            tabs=[{"label": "iPhone"}, {"label": "Galaxy"}],
            children=["iphone_card", "galaxy_card"],
            component_id="main_tabs",
        )
        iphone = create_card("iPhone 16", [], component_id="iphone_card")
        galaxy = create_card("Galaxy S25", [], component_id="galaxy_card")

        artifact = UIArtifact(
            title="Phone Comparison",
            components=[tab_comp, iphone, galaxy],
            root_ids=["main_tabs"],
            data={},
        )

        d = artifact.to_dict()
        tabs_data = d["components"][0]
        assert tabs_data["type"] == "tabs"
        assert tabs_data["children"] == ["iphone_card", "galaxy_card"]
        assert tabs_data["props"]["tabs"] == [{"label": "iPhone"}, {"label": "Galaxy"}]
        assert d["root_ids"] == ["main_tabs"]


class TestInlineArtifactQueue:
    """Tests for InlineArtifactQueue push/pop/has_pending lifecycle."""

    def test_empty_queue(self):
        queue = InlineArtifactQueue()
        assert not queue.has_pending_events()
        assert queue.pop_events() == []

    def test_push_and_pop(self):
        queue = InlineArtifactQueue()
        event = InlineArtifactEvent(
            artifact_id="inline_abc",
            filename="test.png",
            artifact_type=ArtifactType.IMAGE,
            content_type="image/png",
            preview_url="https://example.com/test.png",
        )
        queue.push(event)

        assert queue.has_pending_events()
        events = queue.pop_events()
        assert len(events) == 1
        assert events[0].artifact_id == "inline_abc"
        assert events[0].preview_url == "https://example.com/test.png"

    def test_pop_clears_queue(self):
        queue = InlineArtifactQueue()
        queue.push(
            InlineArtifactEvent(
                artifact_id="a",
                filename="a.png",
                artifact_type=ArtifactType.IMAGE,
                content_type="image/png",
                preview_url="https://a.com/a.png",
            )
        )
        queue.pop_events()
        assert not queue.has_pending_events()
        assert queue.pop_events() == []

    def test_multiple_events(self):
        queue = InlineArtifactQueue()
        for i in range(3):
            queue.push(
                InlineArtifactEvent(
                    artifact_id=f"inline_{i}",
                    filename=f"img{i}.png",
                    artifact_type=ArtifactType.IMAGE,
                    content_type="image/png",
                    preview_url=f"https://x.com/{i}.png",
                )
            )
        events = queue.pop_events()
        assert len(events) == 3
        assert [e.artifact_id for e in events] == ["inline_0", "inline_1", "inline_2"]

    def test_pop_returns_copy(self):
        """pop_events returns a copy; original list is cleared."""
        queue = InlineArtifactQueue()
        queue.push(
            InlineArtifactEvent(
                artifact_id="x",
                filename="x.png",
                artifact_type=ArtifactType.IMAGE,
                content_type="image/png",
                preview_url="https://x.com/x.png",
            )
        )
        events = queue.pop_events()
        assert len(events) == 1
        # Queue should be empty now, but returned list still has the event
        queue.push(
            InlineArtifactEvent(
                artifact_id="y",
                filename="y.png",
                artifact_type=ArtifactType.IMAGE,
                content_type="image/png",
                preview_url="https://x.com/y.png",
            )
        )
        assert len(events) == 1  # Original returned list unchanged


class TestPushInlineArtifact:
    """Tests for push_inline_artifact() context-aware function."""

    def test_push_within_context(self):
        with ArtifactContextManager(message_id="msg_push") as ctx:
            push_inline_artifact(
                filename="generated_dall-e-3.png",
                preview_url="https://oai.com/img.png",
                artifact_type=ArtifactType.IMAGE,
                content_type="image/png",
            )
            events = ctx.inline_artifact_queue.pop_events()
            assert len(events) == 1
            assert events[0].filename == "generated_dall-e-3.png"
            assert events[0].preview_url == "https://oai.com/img.png"
            assert events[0].artifact_id.startswith("inline_")

    def test_push_without_context_no_error(self):
        """push_inline_artifact outside ArtifactContext should silently skip."""
        assert get_artifact_context() is None
        push_inline_artifact(filename="orphan.png", preview_url="https://example.com/orphan.png")

    def test_push_generates_deterministic_id(self):
        """Same URL produces same artifact_id."""
        with ArtifactContextManager():
            push_inline_artifact(filename="a.png", preview_url="https://x.com/same.png")
            push_inline_artifact(filename="b.png", preview_url="https://x.com/same.png")
            ctx = get_artifact_context()
            assert ctx is not None
            events = ctx.inline_artifact_queue.pop_events()
            assert events[0].artifact_id == events[1].artifact_id

    def test_push_different_urls_different_ids(self):
        with ArtifactContextManager():
            push_inline_artifact(filename="a.png", preview_url="https://x.com/a.png")
            push_inline_artifact(filename="b.png", preview_url="https://x.com/b.png")
            ctx = get_artifact_context()
            assert ctx is not None
            events = ctx.inline_artifact_queue.pop_events()
            assert events[0].artifact_id != events[1].artifact_id

    def test_push_default_values(self):
        """Default artifact_type=IMAGE, content_type=image/png."""
        with ArtifactContextManager() as ctx:
            push_inline_artifact(filename="test.png", preview_url="https://example.com/test.png")
            events = ctx.inline_artifact_queue.pop_events()
            assert events[0].artifact_type == ArtifactType.IMAGE
            assert events[0].content_type == "image/png"

    def test_push_custom_type(self):
        with ArtifactContextManager() as ctx:
            push_inline_artifact(
                filename="diagram.svg",
                preview_url="https://example.com/diagram.svg",
                artifact_type=ArtifactType.SVG,
                content_type="image/svg+xml",
            )
            events = ctx.inline_artifact_queue.pop_events()
            assert events[0].artifact_type == ArtifactType.SVG
            assert events[0].content_type == "image/svg+xml"


class TestGetInlineArtifactQueue:
    """Tests for get_inline_artifact_queue()."""

    def test_returns_none_outside_context(self):
        assert get_inline_artifact_queue() is None

    def test_returns_queue_within_context(self):
        with ArtifactContextManager():
            queue = get_inline_artifact_queue()
            assert queue is not None
            assert isinstance(queue, InlineArtifactQueue)

    def test_same_queue_instance(self):
        with ArtifactContextManager() as ctx:
            queue = get_inline_artifact_queue()
            assert queue is ctx.inline_artifact_queue
