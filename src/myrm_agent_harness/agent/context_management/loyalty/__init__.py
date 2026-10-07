"""Package facade for loyalty.

[INPUT]
- agent.context_management.loyalty.loyalty_types::InContextRLExemplar, ModelNeutralizedPrompt,
  ModelVendorFamily, UserLoyaltyPreference, UserLoyaltyStackConfig (POS: Types and models for loyalty.)
- agent.context_management.loyalty.user_loyalty_context_stack::UserLoyaltyContextStack (POS: Manages
  user-centric loyalty layers and cross-model test-time RL alignment.)

[OUTPUT]
- Re-exports: InContextRLExemplar, ModelNeutralizedPrompt, ModelVendorFamily, UserLoyaltyPreference,
  UserLoyaltyStackConfig, UserLoyaltyContextStack

[POS]
Package facade for loyalty.
"""

# ============================================================================
# Loyalty & In-Context RL Alignment Subpackage (Item 150)
# ============================================================================

from .loyalty_types import (
    InContextRLExemplar,
    ModelNeutralizedPrompt,
    ModelVendorFamily,
    UserLoyaltyPreference,
    UserLoyaltyStackConfig,
)
from .user_loyalty_context_stack import UserLoyaltyContextStack

__all__ = [
    "InContextRLExemplar",
    "ModelNeutralizedPrompt",
    "ModelVendorFamily",
    "UserLoyaltyPreference",
    "UserLoyaltyStackConfig",
    "UserLoyaltyContextStack",
]
