"""Who wrote a HumanMessage: the user, or the runtime acting on the user's behalf.

The runtime appends HumanMessages behind the user's (working board, file-restore and sub-agent notices) and marks
them ``is_system_synthetic``. Middlewares that act on what the user said must skip those.

[INPUT]
- langchain_core.messages::BaseMessage, HumanMessage

[OUTPUT]
- is_user_authored_human_message: True for a HumanMessage the user wrote, False for runtime-injected ones and other
  message types

[POS]
Message-provenance predicate shared by the approval and security middlewares.
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage


def is_user_authored_human_message(msg: BaseMessage) -> bool:
    """Determine whether a message represents authentic user input rather than synthetic runtime injection."""
    if not isinstance(msg, HumanMessage):
        return False

    kwargs = getattr(msg, "additional_kwargs", {})
    if not isinstance(kwargs, dict):
        return True

    # Explicit synthetic flag
    if kwargs.get("is_system_synthetic") is True:
        return False

    return kwargs.get("source") not in ("runtime", "system", "working_memory")
