"""DesktopSession — semantic desktop control with @dref registry.

[INPUT]
- dref, perception, execution.healer, session, types, security.credential_vault modules

[OUTPUT]
- DesktopSession: AX snapshot, @dref registry, interact/vision, permissions, inspector export
- create_desktop_session(...) -> DesktopSession

[POS]
Semantic desktop control session. Bridges AX perception, @dref registry, coordinate fallback, and WebUI view updates.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from myrm_agent_harness.toolkits.computer_use.execution.healer import try_bbox_click
from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import (
    capture_snapshot,
    inspect_backend,
    invoke_element,
)
from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import refs_for_view_update
from myrm_agent_harness.toolkits.computer_use.perception.renderer import render_snapshot_tree
from myrm_agent_harness.toolkits.computer_use.som_overlay import (
    apply_som_overlay_to_jpeg_base64,
    build_som_index_map,
)
from myrm_agent_harness.toolkits.computer_use.session import ComputerSession, create_computer_session
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ComputerUseConfig,
    DesktopInteractAction,
    DesktopVisionAction,
    ForegroundPermissionCallback,
    ModifierKey,
    PermissionStatus,
    ScrollDirection,
)
from myrm_agent_harness.toolkits.computer_use.dref.errors import (
    AXPermissionRequiredError,
    AXTreeEmptyError,
    DRefStaleError,
)
from myrm_agent_harness.toolkits.computer_use.dref.registry import DRefRegistry
from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef, SnapshotScope

logger = logging.getLogger(__name__)

ViewUpdateCallback = Callable[[dict[str, object]], None]


class DesktopSession(ComputerSession):
    """Computer session extended with AX snapshot, @dref registry, and view updates."""

    def __init__(
        self,
        backend: object,
        config: ComputerUseConfig | None = None,
        view_update_callback: ViewUpdateCallback | None = None,
        permission_callback: ForegroundPermissionCallback | None = None,
    ) -> None:
        super().__init__(backend=backend, config=config, permission_callback=permission_callback)  # type: ignore[arg-type]
        self._refs = DRefRegistry()
        self._view_update_callback = view_update_callback
        self._last_tree_text: str = ""
        self._last_snapshot_time: float = 0.0

    @property
    def ref_registry(self) -> DRefRegistry:
        return self._refs

    def set_view_update_callback(self, callback: ViewUpdateCallback | None) -> None:
        self._view_update_callback = callback

    def _snapshot_screen_fields(self) -> dict[str, int | float]:
        info = self.screen_info
        return {
            "screen_width": info.width,
            "screen_height": info.height,
            "dpi_scale": info.dpi_scale,
        }

    def _annotate_screenshot_som(
        self,
        screenshot_b64: str,
        refs: dict[str, ElementRef],
        som_index_map: dict[str, int] | None,
    ) -> str:
        if not screenshot_b64 or not som_index_map or self.scaler is None:
            return screenshot_b64
        return apply_som_overlay_to_jpeg_base64(
            screenshot_b64,
            refs,
            self.scaler,
            som_index_map,
        )

    async def desktop_inspect(self) -> str:
        info = inspect_backend(self._backend)
        lines = [
            f"App: {info.get('app_name', '') or 'unknown'}",
            f"Window: {info.get('window_title', '') or 'unknown'}",
            f"Interactive estimate: {info.get('interactive_estimate', 0)}",
            f"Needs permission: {info.get('needs_permission', False)}",
            f"Recommendation: {info.get('recommendation', '')}",
        ]
        return "\n".join(lines)

    async def desktop_snapshot(
        self,
        scope: SnapshotScope = "foreground",
        window_title: str | None = None,
        include_screenshot: bool = False,
    ) -> str | list[object]:
        from myrm_agent_harness.toolkits.computer_use import safety

        try:
            meta, refs = capture_snapshot(self._backend, scope, window_title)
        except AXPermissionRequiredError as exc:
            await self._emit_permission_view_update()
            return str(exc)
        except AXTreeEmptyError as exc:
            return str(exc)

        blocked = safety.is_sensitive_app(meta.app_name, meta.window_title)
        if blocked:
            logger.warning("[SECURITY] Sensitive app guard: %s (app=%s)", blocked, meta.app_name)
            return f"Safety: {blocked}"

        self._refs.replace(refs, meta)
        som_index_map = build_som_index_map(refs) if include_screenshot else None
        tree_text, enriched_meta = render_snapshot_tree(meta, refs, som_index_map=som_index_map)
        self._last_tree_text = tree_text
        self._last_snapshot_time = time.time()

        screenshot_b64 = ""
        screenshot_size = (0, 0)
        if include_screenshot:
            shot = await self.take_screenshot()
            screenshot_b64 = self._annotate_screenshot_som(
                shot.screenshot_base64,
                refs,
                som_index_map,
            )
            screenshot_size = shot.screenshot_size

        await self._emit_view_update(
            screenshot_base64=screenshot_b64,
            screenshot_size=screenshot_size,
            refs=refs,
            meta=enriched_meta,
            som_index_map=som_index_map,
        )

        header = f"Desktop snapshot ready ({enriched_meta.ref_count} refs, ~{enriched_meta.token_estimate} tokens)."
        if include_screenshot and screenshot_b64:
            from langchain_core.messages.content import ContentBlock, create_image_block, create_text_block

            blocks: list[ContentBlock] = [
                create_text_block(f"{header}\n\n{tree_text}"),
                create_image_block(base64=screenshot_b64, mime_type="image/jpeg"),
            ]
            return blocks
        return f"{header}\n\n{tree_text}"

    async def desktop_interact(
        self,
        ref: str,
        action: DesktopInteractAction,
        text: str = "",
        verify_goal: str | None = None,
        modifiers: list[ModifierKey] | None = None,
    ) -> str | list[object]:
        from myrm_agent_harness.toolkits.computer_use import safety

        del verify_goal  # reserved for roadmap #7

        # [SECURITY] Re-validation: If it's been > 5 seconds since the last snapshot,
        # it's highly likely the execution was delayed (e.g., human-in-the-loop approval).
        # The screen might have changed, causing a stale coordinate click. Re-verify silently.
        revalidation_threshold = 5.0
        if time.time() - self._last_snapshot_time > revalidation_threshold:
            logger.info(
                "[SECURITY] Re-validating desktop state before interaction (delayed %.1fs)",
                time.time() - self._last_snapshot_time,
            )
            try:
                meta, refs = capture_snapshot(self._backend, "foreground", None)
                blocked = safety.is_sensitive_app(meta.app_name, meta.window_title)
                if blocked:
                    logger.warning("[SECURITY] Sensitive app guard (interact): %s", blocked)
                    return f"Safety: {blocked}"
                if ref not in refs:
                    return f"Safety Re-validation failed: The screen has changed significantly during approval. The target element '@{ref}' is no longer found. Please take a new snapshot to refresh the view and try again."
                self._refs.replace(refs, meta)
                self._last_snapshot_time = time.time()
            except Exception as e:
                return f"Safety Re-validation failed: Could not re-verify screen state ({e!s})."

        try:
            element = self._refs.get(ref)
        except DRefStaleError as exc:
            return str(exc)

        effective_action = action
        effective_text = text

        if action == "fill_credential":
            from myrm_agent_harness.core.security.credential_vault import get_global_credential_vault

            vault = get_global_credential_vault()
            is_totp = text.endswith("-totp")
            try:
                if is_totp:
                    effective_text = vault.get_totp_token(text)
                else:
                    effective_text = vault.get_password(text)
            except Exception as e:
                return f"Failed to retrieve credential for label '{text}': {e}"
            effective_action = "fill"

        ax_result = invoke_element(self._backend, element, effective_action, effective_text)
        if not ax_result.success:
            bbox_result = await try_bbox_click(self, element, effective_action, effective_text, modifiers)
            if not bbox_result.success:
                return (
                    f"desktop_interact failed for @{element.ref_id}: "
                    f"{ax_result.error}; bbox fallback: {bbox_result.error}"
                )
        else:
            pass

        await asyncio.sleep(self._config.screenshot_delay)
        follow_up = await self.desktop_snapshot(scope="foreground", include_screenshot=False)
        if action == "fill_credential":
            result_prefix = f"Filled credential '{text}' into @{element.ref_id} [CREDENTIAL_FILLED]\n\n"
        else:
            result_prefix = f"Action '{action}' on @{element.ref_id} succeeded.\n\n"
        if isinstance(follow_up, list):
            first = follow_up[0]
            if hasattr(first, "text"):
                first.text = result_prefix + getattr(first, "text", "")
            return follow_up
        return f"{result_prefix}{follow_up}"

    async def desktop_vision_capture(self) -> str | list[object]:
        result = await self.take_screenshot()
        if not result.success:
            return f"Capture failed: {result.error}"
        return self._build_multimodal_response(result, "Desktop vision capture.")

    async def desktop_vision_action(
        self,
        action: DesktopVisionAction,
        coordinate: list[int] | None = None,
        text: str | None = None,
        scroll_direction: ScrollDirection | None = None,
        scroll_amount: int = 3,
        start_coordinate: list[int] | None = None,
        duration: float = 2.0,
        modifiers: list[ModifierKey] | None = None,
    ) -> str | list[object]:
        from myrm_agent_harness.toolkits.computer_use import safety

        # [SECURITY] Sensitive app guard — lightweight foreground app check.
        fg_info = inspect_backend(self._backend)
        blocked = safety.is_sensitive_app(
            fg_info.get("app_name", ""), fg_info.get("window_title", ""),  # type: ignore[arg-type]
        )
        if blocked:
            logger.warning("[SECURITY] Sensitive app guard (vision): %s", blocked)
            return f"Safety: {blocked}"

        # [SECURITY] Foreground permission gate for coordinate-based actions.
        if safety.is_foreground_required(action):
            permission_denied = await self.check_foreground_permission(
                reason=f"Vision action '{action}' requires foreground mouse/keyboard control",
                operation=f"desktop_vision_action({action})",
                estimated_duration_seconds=5.0,
            )
            if permission_denied is not None:
                return f"Permission denied: {permission_denied.error}"

        # [SECURITY] Hard fuse for coordinate-based actions
        revalidation_threshold = 5.0
        if time.time() - self._last_snapshot_time > revalidation_threshold:
            logger.warning(
                "[SECURITY] Coordinate action blocked due to timeout (delayed %.1fs)",
                time.time() - self._last_snapshot_time,
            )
            return "Safety Re-validation failed: The action was delayed (likely by approval) and pixel coordinates are now considered stale and unsafe. Please use 'desktop_snapshot_tool' to take a new screenshot and replan the coordinate."

        if action in ("left_click", "right_click", "middle_click", "double_click", "triple_click"):
            if coordinate is None or len(coordinate) != 2:
                return "Error: coordinate [x, y] is required for click actions"
            clicks = {"double_click": 2, "triple_click": 3}.get(action, 1)
            button = {"right_click": "right", "middle_click": "middle"}.get(action, "left")
            result = await self.click_at(
                coordinate[0],
                coordinate[1],
                button=button,
                clicks=clicks,
                modifiers=modifiers,
            )
        elif action == "type":
            if not text:
                return "Error: text is required for type action"
            text_blocked = safety.is_dangerous_type_text(text)
            if text_blocked:
                return f"Safety: {text_blocked}"
            result = await self.type_text(text)
        elif action == "key":
            if not text:
                return "Error: text (key combo) is required for key action"
            key_blocked = safety.is_blocked_key_combo(text)
            if key_blocked:
                return f"Safety: {key_blocked}"
            result = await self.key_press(text)
        elif action == "scroll":
            if coordinate is None or len(coordinate) != 2 or not scroll_direction:
                return "Error: coordinate and scroll_direction are required for scroll"
            result = await self.scroll_at(
                coordinate[0],
                coordinate[1],
                scroll_direction,
                scroll_amount,
                modifiers=modifiers,
            )
        elif action == "drag":
            if start_coordinate is None or coordinate is None:
                return "Error: start_coordinate and coordinate are required for drag"
            result = await self.drag(
                start_coordinate[0],
                start_coordinate[1],
                coordinate[0],
                coordinate[1],
                modifiers=modifiers,
            )
        elif action == "mouse_move":
            if coordinate is None or len(coordinate) != 2:
                return "Error: coordinate [x, y] is required for mouse_move"
            result = await self.mouse_move_to(coordinate[0], coordinate[1])
        elif action in ("capture", "screenshot"):
            return await self.desktop_vision_capture()
        elif action == "wait":
            result = await self.wait_seconds(duration)
        else:
            return f"Error: unknown vision action '{action}'"

        if not result.success:
            return f"Vision action '{action}' failed: {result.error}"
        if result.screenshot_base64:
            return self._build_multimodal_response(result, f"Vision action '{action}' completed.")
        return f"Vision action '{action}' completed."

    def _build_multimodal_response(self, result: ActionResult, action_description: str) -> list[object]:
        from langchain_core.messages.content import ContentBlock, create_image_block, create_text_block

        info = self.screen_info
        ctx = self.screen_context
        context_parts = [
            action_description,
            f"Screen: {info.width}x{info.height}, DPI: {info.dpi_scale}x. "
            f"Image size: {result.screenshot_size[0]}x{result.screenshot_size[1]}.",
        ]
        if ctx.active_window:
            context_parts.append(f"Active window: {ctx.active_window}")
        context_parts.append(f"Mouse position: ({ctx.mouse_x}, {ctx.mouse_y})")
        if result.output:
            context_parts.append(result.output)
        blocks: list[ContentBlock] = [
            create_text_block("\n".join(context_parts)),
            create_image_block(base64=result.screenshot_base64, mime_type="image/jpeg"),
        ]
        return blocks

    async def _emit_view_update(
        self,
        *,
        screenshot_base64: str,
        screenshot_size: tuple[int, int],
        refs: dict[str, object],
        meta: object,
        som_index_map: dict[str, int] | None = None,
    ) -> None:
        from myrm_agent_harness.core.events.types import AgentEventType
        from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef, SnapshotMeta
        from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

        assert isinstance(meta, SnapshotMeta)
        element_refs = {key: value for key, value in refs.items() if isinstance(value, ElementRef)}
        viewport_width = screenshot_size[0] or self.screen_info.width
        viewport_height = screenshot_size[1] or self.screen_info.height
        payload = {
            "screenshot_base64": screenshot_base64,
            "mime_type": "image/jpeg" if screenshot_base64 else "",
            "refs": refs_for_view_update(
                element_refs,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                som_index_map=som_index_map,
            ),
            "app_name": meta.app_name,
            "window_title": meta.window_title,
            "scope": meta.scope,
            "needs_permission": meta.needs_permission,
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            **self._snapshot_screen_fields(),
        }
        if self._view_update_callback is not None:
            self._view_update_callback(payload)

        sink = get_tool_progress_sink()
        if sink is not None:
            await sink.emit(
                {
                    "type": AgentEventType.DESKTOP_VIEW_UPDATE.value,
                    "data": payload,
                }
            )

    async def _emit_permission_view_update(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.dref.types import SnapshotMeta

        meta = SnapshotMeta(
            ref_count=0,
            app_name="",
            window_title="",
            scope="foreground",
            needs_permission=True,
        )
        await self._emit_view_update(
            screenshot_base64="",
            screenshot_size=(0, 0),
            refs={},
            meta=meta,
        )

    async def check_permissions(self) -> PermissionStatus:
        """Delegate to the platform backend to probe OS-level permissions."""
        return await super().check_permissions()

    async def export_inspector_snapshot(self) -> dict[str, object]:
        """Capture foreground desktop state for WebUI inspector refresh."""
        from myrm_agent_harness.toolkits.computer_use.dref.types import ElementRef

        try:
            meta, refs = capture_snapshot(self._backend, "foreground", None)
        except AXPermissionRequiredError:
            await self._emit_permission_view_update()
            info = self.screen_info
            return {
                "screenshot_base64": "",
                "mime_type": "",
                "refs": {},
                "app_name": "",
                "window_title": "",
                "scope": "foreground",
                "needs_permission": True,
                "viewport_width": info.width,
                "viewport_height": info.height,
                **self._snapshot_screen_fields(),
            }

        self._refs.replace(refs, meta)
        som_index_map = build_som_index_map(refs)
        shot = await self.take_screenshot()
        screenshot_b64 = shot.screenshot_base64 if shot.success else ""
        screenshot_size = shot.screenshot_size if shot.success else (0, 0)
        element_refs = {key: value for key, value in refs.items() if isinstance(value, ElementRef)}
        if screenshot_b64:
            screenshot_b64 = self._annotate_screenshot_som(screenshot_b64, element_refs, som_index_map)
        viewport_width = screenshot_size[0] or self.screen_info.width
        viewport_height = screenshot_size[1] or self.screen_info.height

        await self._emit_view_update(
            screenshot_base64=screenshot_b64,
            screenshot_size=screenshot_size,
            refs=refs,
            meta=meta,
            som_index_map=som_index_map,
        )

        return {
            "screenshot_base64": screenshot_b64,
            "mime_type": "image/jpeg" if screenshot_b64 else "",
            "refs": refs_for_view_update(
                element_refs,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                som_index_map=som_index_map,
            ),
            "app_name": meta.app_name,
            "window_title": meta.window_title,
            "scope": meta.scope,
            "needs_permission": meta.needs_permission,
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            **self._snapshot_screen_fields(),
        }


def create_desktop_session(
    config: ComputerUseConfig | None = None,
    view_update_callback: ViewUpdateCallback | None = None,
    permission_callback: ForegroundPermissionCallback | None = None,
) -> DesktopSession:
    base = create_computer_session(config=config)
    return DesktopSession(
        backend=base._backend,
        config=base._config,
        view_update_callback=view_update_callback,
        permission_callback=permission_callback,
    )
