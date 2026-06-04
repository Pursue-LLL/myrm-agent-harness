import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)

class ExecutionInterceptor(Protocol):
    """Protocol for intercepting code execution actions."""
    
    async def before_destructive_action(self, workspace_path: str, action_type: str, payload: dict) -> None:
        """Called before a destructive action (e.g., file write, rm, sed) is executed.
        
        Args:
            workspace_path: The root path of the workspace.
            action_type: The type of action ('bash', 'file_write', 'file_delete', etc.).
            payload: Additional details about the action.
        """
        ...

_interceptor: ExecutionInterceptor | None = None

def set_execution_interceptor(interceptor: ExecutionInterceptor | None) -> None:
    """Set the global execution interceptor."""
    global _interceptor
    _interceptor = interceptor

def get_execution_interceptor() -> ExecutionInterceptor | None:
    """Get the global execution interceptor."""
    return _interceptor

async def trigger_destructive_action_hook(workspace_path: str, action_type: str, payload: dict) -> None:
    """Safely trigger the interceptor with a timeout, ensuring it never blocks execution."""
    interceptor = get_execution_interceptor()
    if not interceptor:
        return
        
    try:
        # 3 second timeout to ensure we never block the main execution flow
        await asyncio.wait_for(
            interceptor.before_destructive_action(workspace_path, action_type, payload),
            timeout=3.0
        )
    except asyncio.TimeoutError:
        logger.warning(f"ExecutionInterceptor timeout after 3.0s for {action_type}")
    except Exception as e:
        logger.warning(f"ExecutionInterceptor failed for {action_type}: {e}")
