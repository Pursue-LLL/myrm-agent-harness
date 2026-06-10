"""Checkpointer factory mode validation."""

import pytest

from myrm_agent_harness.runtime.checkpointing.factory import create_checkpointer


@pytest.mark.asyncio
async def test_unsupported_checkpointer_mode_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported checkpointer mode"):
        await create_checkpointer(mode="postgres")
