"""Tests for the Tool Registry — tool name → permission type mapping + safety metadata."""

import pytest

from myrm_agent_harness.agent.security.tool_registry import (
    BUILTIN_TOOL_NAMES,
    TOOL_PERMISSION_MAP,
    TOOL_SAFETY_METADATA,
    SafetyMetadata,
    resolve_permission_type,
    resolve_safety_metadata,
)


class TestToolPermissionMap:
    def test_code_execution_tools_map_correctly(self):
        assert TOOL_PERMISSION_MAP["bash_code_execute_tool"] == "code_interpreter"
        assert "code_interpreter_tool" not in TOOL_PERMISSION_MAP
        assert "bash_tool" not in TOOL_PERMISSION_MAP

    def test_file_tools_map_correctly(self):
        assert TOOL_PERMISSION_MAP["file_read_tool"] == "file_read"
        assert TOOL_PERMISSION_MAP["file_write_tool"] == "file_write"
        assert TOOL_PERMISSION_MAP["file_edit_tool"] == "file_write"
        assert TOOL_PERMISSION_MAP["grep_tool"] == "file_read"
        assert TOOL_PERMISSION_MAP["glob_tool"] == "file_read"

    def test_web_fetch_maps_to_net_fetch(self):
        assert TOOL_PERMISSION_MAP["web_fetch_tool"] == "net_fetch"

    def test_agent_and_cron_tools_map_correctly(self):
        assert TOOL_PERMISSION_MAP["delegate_to_agent_tool"] == "delegate_agent"
        assert TOOL_PERMISSION_MAP["cron_manage_tool"] == "cron_manage"
        assert TOOL_PERMISSION_MAP["skill_manage_tool"] == "skill_manage"


class TestBuiltinToolNames:
    def test_contains_all_mapped_tools(self):
        for tool_name in TOOL_PERMISSION_MAP:
            assert tool_name in BUILTIN_TOOL_NAMES

    def test_contains_unmapped_builtins(self):
        assert "web_search_tool" in BUILTIN_TOOL_NAMES
        assert "memory_recall_tool" in BUILTIN_TOOL_NAMES
        assert "memory_save_tool" in BUILTIN_TOOL_NAMES
        assert "memory_manage_tool" in BUILTIN_TOOL_NAMES
        assert "skill_select_tool" in BUILTIN_TOOL_NAMES
        assert "skill_discovery_tool" in BUILTIN_TOOL_NAMES
        assert "discover_capability_tool" in BUILTIN_TOOL_NAMES
        assert "request_answer_user_tool" in BUILTIN_TOOL_NAMES
        assert "render_ui_tool" in BUILTIN_TOOL_NAMES


class TestResolvePermissionType:
    def test_mapped_tool_returns_permission_type(self):
        assert resolve_permission_type("bash_code_execute_tool") == "code_interpreter"
        assert resolve_permission_type("file_read_tool") == "file_read"
        assert resolve_permission_type("file_edit_tool") == "file_write"
        assert resolve_permission_type("web_fetch_tool") == "net_fetch"

    def test_unmapped_builtin_returns_original_name(self):
        assert resolve_permission_type("web_search_tool") == "web_search_tool"
        assert resolve_permission_type("memory_recall_tool") == "memory_recall_tool"
        assert resolve_permission_type("skill_select_tool") == "skill_select_tool"
        assert resolve_permission_type("request_answer_user_tool") == "request_answer_user_tool"
        assert resolve_permission_type("render_ui_tool") == "render_ui_tool"
        assert resolve_permission_type("discover_capability_tool") == "discover_capability_tool"

    def test_mapped_agent_tools_return_permission_type(self):
        assert resolve_permission_type("delegate_to_agent_tool") == "delegate_agent"
        assert resolve_permission_type("cron_manage_tool") == "cron_manage"
        assert resolve_permission_type("skill_manage_tool") == "skill_manage"

    def test_unknown_tool_returns_mcp_invoke(self):
        assert resolve_permission_type("search-web") == "mcp_invoke"
        assert resolve_permission_type("get-weather") == "mcp_invoke"
        assert resolve_permission_type("custom_mcp_tool") == "mcp_invoke"

    def test_mcp_prefixed_tool_returns_mcp_invoke(self):
        assert resolve_permission_type("mcp__github__search_repos") == "mcp_invoke"
        assert resolve_permission_type("mcp__filesystem__read_file") == "mcp_invoke"

    def test_empty_string_returns_mcp_invoke(self):
        assert resolve_permission_type("") == "mcp_invoke"


class TestBrowserToolMapping:
    """Browser tools: static and dynamic permission resolution."""

    def test_static_browser_tools(self):
        assert resolve_permission_type("browser_navigate_tool") == "browser_navigate"
        assert resolve_permission_type("browser_snapshot_tool") == "browser_read"
        assert resolve_permission_type("browser_extract_tool") == "browser_read"

    def test_browser_interact_and_manage_are_builtin(self):
        assert "browser_interact_tool" in BUILTIN_TOOL_NAMES
        assert "browser_manage_tool" in BUILTIN_TOOL_NAMES

    def test_interact_click_resolves(self):
        assert resolve_permission_type("browser_interact_tool", {"action": "click"}) == "browser_click"

    def test_interact_fill_resolves(self):
        assert resolve_permission_type("browser_interact_tool", {"action": "fill"}) == "browser_fill"

    def test_interact_type_resolves_to_fill(self):
        assert resolve_permission_type("browser_interact_tool", {"action": "type"}) == "browser_fill"

    def test_interact_upload_resolves(self):
        assert resolve_permission_type("browser_interact_tool", {"action": "upload_file"}) == "browser_upload"

    def test_interact_hover_resolves_to_click(self):
        assert resolve_permission_type("browser_interact_tool", {"action": "hover"}) == "browser_click"

    def test_interact_scroll_resolves(self):
        assert resolve_permission_type("browser_interact_tool", {"action": "scroll"}) == "browser_scroll"

    def test_manage_evaluate_resolves(self):
        assert resolve_permission_type("browser_manage_tool", {"action": "evaluate"}) == "browser_evaluate"

    def test_manage_list_tabs_resolves(self):
        assert resolve_permission_type("browser_manage_tool", {"action": "list_tabs"}) == "browser_manage"

    def test_manage_close_resolves(self):
        assert resolve_permission_type("browser_manage_tool", {"action": "close"}) == "browser_manage"

    def test_manage_download_resolves(self):
        assert resolve_permission_type("browser_manage_tool", {"action": "download_url"}) == "browser_download"

    def test_interact_without_input_falls_to_builtin(self):
        assert resolve_permission_type("browser_interact_tool") == "browser_interact_tool"

    def test_manage_without_input_falls_to_builtin(self):
        assert resolve_permission_type("browser_manage_tool") == "browser_manage_tool"


class TestSafetyMetadata:
    """Safety metadata: opt-in whitelist with fail-closed defaults."""

    def test_fail_closed_defaults_for_undeclared_tool(self):
        meta = resolve_safety_metadata("some_unknown_mcp_tool")
        assert meta.is_read_only is False
        assert meta.is_concurrent_safe is False
        assert meta.is_destructive is False

    def test_destructive_tools_declared(self):
        for tool in (
            "bash_code_execute_tool",
            "file_write_tool",
            "file_edit_tool",
        ):
            meta = resolve_safety_metadata(tool)
            assert meta.is_destructive is True, f"{tool} should be destructive"
            assert meta.is_concurrent_safe is False, f"{tool} should not be concurrent-safe"
            assert meta.is_read_only is False, f"{tool} should not be read-only"

    def test_read_tools_declared_safe(self):
        read_tools = ("file_read_tool", "grep_tool", "glob_tool")
        for tool in read_tools:
            meta = resolve_safety_metadata(tool)
            assert meta.is_read_only is True, f"{tool} should be read-only"
            assert meta.is_concurrent_safe is True, f"{tool} should be concurrent-safe"
            assert meta.is_destructive is False, f"{tool} should not be destructive"

    def test_browser_read_tools_declared_safe(self):
        for tool in ("browser_snapshot_tool", "browser_extract_tool"):
            meta = resolve_safety_metadata(tool)
            assert meta.is_read_only is True
            assert meta.is_concurrent_safe is True

    def test_search_tools_declared_safe(self):
        for tool in ("web_search_tool", "web_fetch_tool", "memory_recall_tool"):
            meta = resolve_safety_metadata(tool)
            assert meta.is_read_only is True
            assert meta.is_concurrent_safe is True

    def test_skill_search_tools_declared_safe(self):
        for tool in ("discover_capability_tool", "skill_discovery_tool"):
            meta = resolve_safety_metadata(tool)
            assert meta.is_read_only is True
            assert meta.is_concurrent_safe is True

    def test_all_builtins_have_safety_metadata(self):
        """Every built-in tool must have explicit safety metadata."""
        missing = BUILTIN_TOOL_NAMES - TOOL_SAFETY_METADATA.keys()
        assert not missing, f"Built-in tools missing TOOL_SAFETY_METADATA: {sorted(missing)}"

    def test_concurrent_safe_agents(self):
        for tool in ("delegate_task_tool", "batch_delegate_tasks_tool"):
            meta = resolve_safety_metadata(tool)
            assert meta.is_concurrent_safe is True, f"{tool} should be concurrent-safe"
            assert meta.is_read_only is False, f"{tool} should not be read-only"

    def test_delegate_to_agent_not_concurrent(self):
        meta = resolve_safety_metadata("delegate_to_agent_tool")
        assert meta.is_concurrent_safe is False
        assert meta.is_read_only is False

    def test_stateful_tools_not_concurrent(self):
        for tool in ("browser_navigate_tool", "browser_interact_tool", "cron_manage_tool", "memory_save_tool"):
            meta = resolve_safety_metadata(tool)
            assert meta.is_concurrent_safe is False, f"{tool} should not be concurrent-safe"

    def test_ui_tools_are_safe(self):
        for tool in ("request_answer_user_tool", "render_ui_tool", "skill_select_tool"):
            meta = resolve_safety_metadata(tool)
            assert meta.is_read_only is True
            assert meta.is_concurrent_safe is True

    def test_metadata_is_frozen(self):
        meta = resolve_safety_metadata("file_read_tool")
        try:
            meta.is_read_only = False  # type: ignore[misc]
            raise AssertionError("SafetyMetadata should be frozen")
        except AttributeError:
            pass

    def test_default_singleton_identity(self):
        """Undeclared tools should return the same default instance."""
        a = resolve_safety_metadata("mcp_tool_a")
        b = resolve_safety_metadata("mcp_tool_b")
        assert a is b

    def test_safety_metadata_dataclass_equality(self):
        assert SafetyMetadata() == SafetyMetadata(is_read_only=False, is_concurrent_safe=False, is_destructive=False)


class TestComputerToolMapping:
    """Desktop control tools: permission resolution and safety metadata."""

    def test_desktop_inspect_maps_to_desktop_capture(self):
        assert resolve_permission_type("desktop_inspect_tool") == "desktop_capture"

    def test_desktop_snapshot_maps_to_desktop_capture(self):
        assert resolve_permission_type("desktop_snapshot_tool") == "desktop_capture"

    def test_desktop_interact_maps_to_desktop_control(self):
        assert resolve_permission_type("desktop_interact_tool") == "desktop_control"

    def test_desktop_vision_capture_maps_to_desktop_capture(self):
        assert resolve_permission_type("desktop_vision_tool", {"action": "capture"}) == "desktop_capture"

    def test_desktop_vision_wait_maps_to_desktop_capture(self):
        assert resolve_permission_type("desktop_vision_tool", {"action": "wait"}) == "desktop_capture"

    def test_desktop_vision_click_maps_to_desktop_control(self):
        assert resolve_permission_type("desktop_vision_tool", {"action": "left_click"}) == "desktop_control"

    def test_desktop_vision_type_maps_to_desktop_control(self):
        assert resolve_permission_type("desktop_vision_tool", {"action": "type"}) == "desktop_control"

    def test_desktop_vision_without_input_maps_to_desktop_control(self):
        assert resolve_permission_type("desktop_vision_tool") == "desktop_control"

    def test_desktop_tools_in_builtins(self):
        assert "desktop_inspect_tool" in BUILTIN_TOOL_NAMES
        assert "desktop_snapshot_tool" in BUILTIN_TOOL_NAMES
        assert "desktop_interact_tool" in BUILTIN_TOOL_NAMES
        assert "desktop_vision_tool" in BUILTIN_TOOL_NAMES

    def test_desktop_snapshot_safety_metadata(self):
        meta = resolve_safety_metadata("desktop_snapshot_tool")
        assert meta.is_read_only is True
        assert meta.is_concurrent_safe is True
        assert meta.is_destructive is False

    def test_desktop_interact_safety_metadata(self):
        meta = resolve_safety_metadata("desktop_interact_tool")
        assert meta.is_destructive is True

    def test_desktop_control_in_default_ruleset(self):
        """Verify desktop_control requires ASK permission in default ruleset."""
        from myrm_agent_harness.agent.security.types import DEFAULT_RULESET, PermissionAction
        desktop_rules = [r for r in DEFAULT_RULESET if r.permission == "desktop_control"]
        assert len(desktop_rules) == 1
        assert desktop_rules[0].action == PermissionAction.ASK


class TestComputeCanonicalArgsHash:
    """Tests for compute_canonical_args_hash — stable hashing of tool arguments."""

    def test_none_args_returns_none(self):
        from myrm_agent_harness.agent.security.tool_registry import compute_canonical_args_hash

        assert compute_canonical_args_hash("bash_code_execute_tool", None) is None

    def test_known_tool_uses_canonical_params(self):
        from myrm_agent_harness.agent.security.tool_registry import TOOL_CANONICAL_PARAMS, compute_canonical_args_hash

        tool_name = next(iter(TOOL_CANONICAL_PARAMS))
        core = TOOL_CANONICAL_PARAMS[tool_name]
        args_full = {k: "val" for k in core}
        args_full["extra_param"] = "noise"

        args_core = {k: "val" for k in core}

        assert compute_canonical_args_hash(tool_name, args_full) == compute_canonical_args_hash(tool_name, args_core)

    def test_unknown_tool_hashes_all_args(self):
        from myrm_agent_harness.agent.security.tool_registry import compute_canonical_args_hash

        h1 = compute_canonical_args_hash("unknown_tool", {"a": 1, "b": 2})
        h2 = compute_canonical_args_hash("unknown_tool", {"b": 2, "a": 1})
        assert h1 == h2
        assert len(h1) == 16

    def test_different_args_different_hash(self):
        from myrm_agent_harness.agent.security.tool_registry import compute_canonical_args_hash

        h1 = compute_canonical_args_hash("unknown_tool", {"a": 1})
        h2 = compute_canonical_args_hash("unknown_tool", {"a": 2})
        assert h1 != h2


class TestCheckSafetyCoverage:
    """Tests for _check_safety_coverage — warning for undeclared built-in tools."""

    def test_check_logs_warning_for_missing_tools(self, monkeypatch: pytest.MonkeyPatch):
        import io
        import logging

        from myrm_agent_harness.core.security.tool_registry import BUILTIN_TOOL_NAMES, _check_safety_coverage

        fake_tool = "__test_fake_builtin_tool__"
        monkeypatch.setattr(
            "myrm_agent_harness.core.security.tool_registry.BUILTIN_TOOL_NAMES", BUILTIN_TOOL_NAMES | {fake_tool}
        )

        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger("myrm_agent_harness.core.security.tool_registry_safety")
        logger.addHandler(handler)
        try:
            _check_safety_coverage()
        finally:
            logger.removeHandler(handler)

        output = log_capture.getvalue()
        assert fake_tool in output

    def test_no_warning_when_all_covered(self):
        import io
        import logging

        from myrm_agent_harness.agent.security.tool_registry import _check_safety_coverage

        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger("myrm_agent_harness.core.security.tool_registry_safety")
        logger.addHandler(handler)
        try:
            _check_safety_coverage()
        finally:
            logger.removeHandler(handler)

        assert "missing" not in log_capture.getvalue().lower()


class TestPtcSafetyMetadata:
    def test_register_get_and_resolve_ptc_tool(self) -> None:
        from myrm_agent_harness.core.security.tool_registry import (
            MCPAnnotations,
            SafetyMetadata,
            get_ptc_safety_metadata,
            register_ptc_safety_metadata,
            resolve_safety_metadata,
        )

        meta = SafetyMetadata(is_read_only=True, is_concurrent_safe=True)
        annotations: MCPAnnotations = {"title": "dynamic"}
        tool_name = "__test_ptc_dynamic_tool__"

        register_ptc_safety_metadata("skill-a", tool_name, meta, annotations)
        assert get_ptc_safety_metadata("skill-a", tool_name) == (meta, annotations)
        assert resolve_safety_metadata(tool_name) == meta


class TestSanitizeUrlForTaint:
    def test_strips_query_and_fragment(self) -> None:
        from myrm_agent_harness.core.security.tool_registry import _sanitize_url_for_taint

        assert _sanitize_url_for_taint("https://example.com/a?token=secret#frag") == "https://example.com/a"

    def test_none_returns_none(self) -> None:
        from myrm_agent_harness.core.security.tool_registry import _sanitize_url_for_taint

        assert _sanitize_url_for_taint(None) is None

    def test_invalid_url_redacted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from myrm_agent_harness.core.security.tool_registry import _sanitize_url_for_taint

        def _boom(_url: str) -> object:
            raise ValueError("parse fail")

        monkeypatch.setattr("urllib.parse.urlparse", _boom)
        assert _sanitize_url_for_taint("https://example.com/x") == "invalid_or_redacted_url"
