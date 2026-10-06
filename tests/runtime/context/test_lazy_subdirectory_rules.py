"""Unit tests for lazy-loaded subdirectory rules discovery and dynamic tool injection."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.runtime.context.lazy_subdirectory_rules import (
    DynamicToolInjectionHub,
    LazySubdirectoryRulesProbe,
)
from myrm_agent_harness.runtime.context.lazy_subdirectory_rules_types import (
    SubdirectoryRuleDiscoveryMode,
)


def test_lazy_probe_finds_rules_in_hierarchy(tmp_path: Path) -> None:
    """Verifies that subdirectory rules are discovered on-demand up to (excluding) workspace root."""
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()

    # Root rule (should be excluded by probe because root is preloaded at startup)
    (ws_root / "AGENTS.md").write_text("Root global instructions", encoding="utf-8")

    # Backend package rule
    backend_dir = ws_root / "packages" / "backend"
    backend_dir.mkdir(parents=True)
    (backend_dir / "AGENTS.md").write_text("Backend rule: Always use async endpoints", encoding="utf-8")

    # Nested service rule
    service_dir = backend_dir / "services" / "payment"
    service_dir.mkdir(parents=True)
    (service_dir / "rules.md").write_text("Payment rule: Mask all credit card numbers", encoding="utf-8")

    target_file = service_dir / "handler.py"
    target_file.write_text("def process(): pass", encoding="utf-8")

    discovered = LazySubdirectoryRulesProbe.find_rules_for_path(
        workspace_root=ws_root,
        target_path=target_file,
    )

    # Should discover payment/rules.md and backend/AGENTS.md, but NOT ws_root/AGENTS.md
    assert len(discovered) == 2
    scopes = [d.directory_scope for d in discovered]
    assert "packages/backend/services/payment" in scopes
    assert "packages/backend" in scopes
    assert "" not in scopes  # Root excluded

    for r in discovered:
        assert len(r.sha256_hash) == 64
        assert r.token_count > 0


def test_lazy_probe_boundary_security(tmp_path: Path) -> None:
    """Verifies that paths outside workspace root are rejected safely without escaping."""
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.py"
    outside_file.write_text("secret = 123", encoding="utf-8")

    discovered = LazySubdirectoryRulesProbe.find_rules_for_path(
        workspace_root=ws_root,
        target_path=outside_file,
    )
    assert discovered == []


def test_dynamic_tool_injection_on_first_access(tmp_path: Path) -> None:
    """Verifies ON_FIRST_ACCESS mode attaches rules on first hit and skips subsequent hits."""
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()
    sub_pkg = ws_root / "apps" / "web"
    sub_pkg.mkdir(parents=True)
    (sub_pkg / ".goosehints").write_text("Web hint: Use Next.js app router", encoding="utf-8")
    target_file = sub_pkg / "page.tsx"
    target_file.write_text("export default function Page() {}", encoding="utf-8")

    hub = DynamicToolInjectionHub()
    session_id = "sess-web-1"
    raw_output = "File content read successfully: 32 bytes"

    # Turn 1: First access -> Rules must be dynamically injected
    env1 = hub.augment_tool_result(
        session_id=session_id,
        workspace_root=ws_root,
        target_path=target_file,
        raw_tool_output=raw_output,
        mode=SubdirectoryRuleDiscoveryMode.ON_FIRST_ACCESS,
    )
    assert env1.was_injected is True
    assert len(env1.injected_rules) == 1
    assert "[Subdirectory Context Rules: apps/web (.goosehints)]" in env1.augmented_tool_output
    assert "Web hint: Use Next.js app router" in env1.augmented_tool_output

    # Turn 2: Second access to the same directory in same session -> Skip injection to preserve cache
    env2 = hub.augment_tool_result(
        session_id=session_id,
        workspace_root=ws_root,
        target_path=target_file,
        raw_tool_output=raw_output,
        mode=SubdirectoryRuleDiscoveryMode.ON_FIRST_ACCESS,
    )
    assert env2.was_injected is False
    assert env2.augmented_tool_output == raw_output
    assert len(env2.injected_rules) == 0


def test_dynamic_tool_injection_always_attach(tmp_path: Path) -> None:
    """Verifies ALWAYS_ATTACH mode attaches rules on every execution."""
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()
    sub_pkg = ws_root / "modules" / "auth"
    sub_pkg.mkdir(parents=True)
    (sub_pkg / ".traerules").write_text("Auth rule: Always use JWT HS256", encoding="utf-8")
    target_file = sub_pkg / "token.py"
    target_file.write_text("jwt_secret = 'xyz'", encoding="utf-8")

    hub = DynamicToolInjectionHub()
    session_id = "sess-auth"
    raw_output = "grep match line 1"

    # Call 1
    env1 = hub.augment_tool_result(
        session_id=session_id,
        workspace_root=ws_root,
        target_path=target_file,
        raw_tool_output=raw_output,
        mode=SubdirectoryRuleDiscoveryMode.ALWAYS_ATTACH,
    )
    assert env1.was_injected is True

    # Call 2
    env2 = hub.augment_tool_result(
        session_id=session_id,
        workspace_root=ws_root,
        target_path=target_file,
        raw_tool_output=raw_output,
        mode=SubdirectoryRuleDiscoveryMode.ALWAYS_ATTACH,
    )
    assert env2.was_injected is True
    assert "[Subdirectory Context Rules: modules/auth (.traerules)]" in env2.augmented_tool_output


def test_session_cache_clearing(tmp_path: Path) -> None:
    """Verifies that clearing session cache permits re-injection under ON_FIRST_ACCESS."""
    ws_root = tmp_path / "workspace"
    ws_root.mkdir()
    sub_pkg = ws_root / "core"
    sub_pkg.mkdir(parents=True)
    (sub_pkg / "AGENTS.md").write_text("Core rule: Strict typing", encoding="utf-8")
    target_file = sub_pkg / "engine.py"
    target_file.write_text("class Engine: pass", encoding="utf-8")

    hub = DynamicToolInjectionHub()
    session_id = "sess-cache-test"
    raw_output = "read file done"

    env1 = hub.augment_tool_result(
        session_id=session_id,
        workspace_root=ws_root,
        target_path=target_file,
        raw_tool_output=raw_output,
    )
    assert env1.was_injected is True

    # Clear cache
    hub.clear_session_cache(session_id)

    # Now it should inject again
    env2 = hub.augment_tool_result(
        session_id=session_id,
        workspace_root=ws_root,
        target_path=target_file,
        raw_tool_output=raw_output,
    )
    assert env2.was_injected is True
