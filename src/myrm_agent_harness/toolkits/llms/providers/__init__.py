# Import for side-effect: each provider module registers itself in litellm.custom_provider_map
from .minimax_image import minimax_image_llm  # noqa: F401
from .yunshu import yunshu_llm  # noqa: F401
