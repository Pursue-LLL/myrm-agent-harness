"""DesktopSession — semantic desktop control with @dref registry.

[INPUT]
- element_ref.registry::DRefRegistry (POS: session-scoped @dref element map)
- element_ref.types::SnapshotScope, SnapshotMeta, ElementRef (POS: shared snapshot types)
- perception.ax_dispatch::capture_snapshot, inspect_backend, invoke_element (POS: platform AX dispatch)
- perception.macos_ax::refs_for_view_update (POS: overlay ref serialization for WebUI)
- perception.renderer::render_snapshot_tree (POS: AX tree text renderer)
- execution.healer::try_bbox_click (POS: BBox coordinate fallback when AX invoke fails)
- session::ComputerSession, create_computer_session (POS: screenshot and coordinate I/O orchestrator)
- types::ComputerUseConfig, ModifierKey, DesktopInteractAction, DesktopVisionAction, ScrollDirection, ActionResult (POS: shared computer_use types)

[OUTPUT]
- DesktopSession: semantic desktop orchestrator with @dref registry and DESKTOP_VIEW_UPDATE emission
  - desktop_inspect() -> str
  - desktop_snapshot(...) -> str | list[ContentBlock]
  - desktop_interact(...) -> str | list[ContentBlock]
  - desktop_vision_capture/action(...) -> str | list[ContentBlock]
  - export_inspector_snapshot() -> dict[str, object]
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
from myrm_agent_harness.toolkits.computer_use.session import ComputerSession, create_computer_session
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ComputerUseConfig,
    DesktopInteractAction,
    DesktopVisionAction,
    ModifierKey,
    ScrollDirection,
)
from myrm_agent_harness.toolkits.element_ref.errors import (
    AXPermissionRequiredError,
    AXTreeEmptyError,
    DRefStaleError,
)
from myrm_agent_harness.toolkits.element_ref.registry import DRefRegistry
from myrm_agent_harness.toolkits.element_ref.types import SnapshotScope

logger = logging.getLogger(__name__)

ViewUpdateCallback = Callable[[dict[str, object]], None]


class DesktopSession(ComputerSession):
    """Computer session extended with AX snapshot, @dref registry, and view updates."""

    def __init__(
        self,
        backend: object,
        config: ComputerUseConfig | None = None,
        view_update_callback: ViewUpdateCallback | None = None,
    ) -> None:
        super().__init__(backend=backend, config=config)  # type: ignore[arg-type]
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
        try:
            meta, refs = capture_snapshot(self._backend, scope, window_title)
        except AXPermissionRequiredError as exc:
            await self._emit_permission_view_update()
            return str(exc)
        except AXTreeEmptyError as exc:
            return str(exc)

        self._refs.replace(refs, meta)
        tree_text, enriched_meta = render_snapshot_tree(meta, refs)
        self._last_tree_text = tree_text
        self._last_snapshot_time = time.time()

        screenshot_b64 = ""
        screenshot_size = (0, 0)
        if include_screenshot:
            shot = await self.take_screenshot()
            screenshot_b64 = shot.screenshot_base64
            screenshot_size = shot.screenshot_size

        await self._emit_view_update(
            screenshot_base64=screenshot_b64,
            screenshot_size=screenshot_size,
            refs=refs,
            meta=enriched_meta,
        )

        header = (
            f"Desktop snapshot ready ({enriched_meta.ref_count} refs, "
            f"~{enriched_meta.token_estimate} tokens)."
        )
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
        del verify_goal  # reserved for roadmap #7

        # [SECURITY] Re-validation: If it's been > 5 seconds since the last snapshot,
        # it's highly likely the execution was delayed (e.g., human-in-the-loop approval).
        # The screen might have changed, causing a stale coordinate click. Re-verify silently.
        revalidation_threshold = 5.0
        if time.time() - self._last_snapshot_time > revalidation_threshold:
            logger.info("[SECURITY] Re-validating desktop state before interaction (delayed %.1fs)", time.time() - self._last_snapshot_time)
            try:
                meta, refs = capture_snapshot(self._backend, "foreground", None)
                if ref not in refs:
                    return f"Safety Re-validation failed: The screen has changed significantly during approval. The target element '@{ref}' is no longer found. Please take a new snapshot to refresh the view and try again."
                # Update registry quietly so the click uses the latest fresh coordinates
                self._refs.replace(refs, meta)
                self._last_snapshot_time = time.time()
            except Exception as e:
                return f"Safety Re-validation failed: Could not re-verify screen state ({e!s})."

        try:
            element = self._refs.get(ref)
        except DRefStaleError as exc:
            return str(exc)

        ax_result = invoke_element(self._backend, element, action, text)
        if not ax_result.success:
            bbox_result = await try_bbox_click(self, element, action, text, modifiers)
            if not bbox_result.success:
                return (
                    f"desktop_interact failed for @{element.ref_id}: "
                    f"{ax_result.error}; bbox fallback: {bbox_result.error}"
                )
        else:
            pass

        await asyncio.sleep(self._config.screenshot_delay)
        follow_up = await self.desktop_snapshot(scope="foreground", include_screenshot=False)
        if isinstance(follow_up, list):
            prefix = f"Action '{action}' on @{element.ref_id} succeeded.\n\n"
            first = follow_up[0]
            if hasattr(first, "text"):
                first.text = prefix + getattr(first, "text", "")
            return follow_up
        return f"Action '{action}' on @{element.ref_id} succeeded.\n\n{follow_up}"

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

        # [SECURITY] Hard fuse for coordinate-based actions
        revalidation_threshold = 5.0
        if time.time() - self._last_snapshot_time > revalidation_threshold:
            logger.warning("[SECURITY] Coordinate action blocked due to timeout (delayed %.1fs)", time.time() - self._last_snapshot_time)
            return "Safety Re-validation failed: The action was delayed (likely by approval) and pixel coordinates are now considered stale and unsafe. Please use 'desktop_snapshot_tool' to take a new screenshot and replan the coordinate."

        if action in ("left_click", "right_click", "middle_click", "double_click", "triple_click"):
            if coordinate is None or len(coordinate) != 2:
                return "Error: coordinate [x, y] is required for click actions"
            clicks = {"double_click": 2, "triple_click": 3}.get(action, 1)
            button = {"right_click": "right", "middle_click": "middle"}.get(action, "left")
            result = await self.click_at(
                coordinate[0], coordinate[1], button=button, clicks=clicks, modifiers=modifiers,
            )
        elif action == "type":
            if not text:
                return "Error: text is required for type action"
            blocked = safety.is_dangerous_type_text(text)
            if blocked:
                return f"Safety: {blocked}"
            result = await self.type_text(text)
        elif action == "key":
            if not text:
                return "Error: text (key combo) is required for key action"
            blocked = safety.is_blocked_key_combo(text)
            if blocked:
                return f"Safety: {blocked}"
            result = await self.key_press(text)
        elif action == "scroll":
            if coordinate is None or len(coordinate) != 2 or not scroll_direction:
                return "Error: coordinate and scroll_direction are required for scroll"
            result = await self.scroll_at(
                coordinate[0], coordinate[1], scroll_direction, scroll_amount, modifiers=modifiers,
            )
        elif action == "drag":
            if start_coordinate is None or coordinate is None:
                return "Error: start_coordinate and coordinate are required for drag"
            result = await self.drag(
                start_coordinate[0], start_coordinate[1], coordinate[0], coordinate[1], modifiers=modifiers,
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
    ) -> None:
        from myrm_agent_harness.core.events.types import AgentEventType
        from myrm_agent_harness.toolkits.element_ref.types import ElementRef, SnapshotMeta
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
            await sink.emit({
                "type": AgentEventType.DESKTOP_VIEW_UPDATE.value,
                "data": payload,
            })

    async def _emit_permission_view_update(self) -> None:
        from myrm_agent_harness.toolkits.element_ref.types import SnapshotMeta

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

    async def export_inspector_snapshot(self) -> dict[str, object]:
        """Capture foreground desktop state for WebUI inspector refresh."""
        from myrm_agent_harness.toolkits.element_ref.types import ElementRef

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
        shot = await self.take_screenshot()
        screenshot_b64 = shot.screenshot_base64 if shot.success else ""
        screenshot_size = shot.screenshot_size if shot.success else (0, 0)
        element_refs = {key: value for key, value in refs.items() if isinstance(value, ElementRef)}
        viewport_width = screenshot_size[0] or self.screen_info.width
        viewport_height = screenshot_size[1] or self.screen_info.height

        await self._emit_view_update(
            screenshot_base64=screenshot_b64,
            screenshot_size=screenshot_size,
            refs=refs,
            meta=meta,
        )

        return {
            "screenshot_base64": screenshot_b64,
            "mime_type": "image/jpeg" if screenshot_b64 else "",
            "refs": refs_for_view_update(
                element_refs,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
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
) -> DesktopSession:
    base = create_computer_session(config=config)
    return DesktopSession(
        backend=base._backend,
        config=base._config,
        view_update_callback=view_update_callback,
    )
