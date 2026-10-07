"""Package facade for pairing.

[INPUT]
- agent.context_management.pairing.fast_pairing_gateway::DeviceAuthVault, LocalDiscoveryBeaconManager,
  PairingQrBootstrapEngine, PasskeyChallengeAuthenticator (POS: Generates dynamic pairing tickets and
  formatted QR code bootstrap payloads.)
- agent.context_management.pairing.pairing_types::AuthChallenge, ChallengeResponse, DeviceTrustState,
  DiscoveredServiceBeacon, PairingTicket, PasskeyAlgorithmKind, PasskeyCredential (POS: Types and models for
  pairing.)

[OUTPUT]
- Re-exports: AuthChallenge, ChallengeResponse, DeviceAuthVault, DeviceTrustState, DiscoveredServiceBeacon,
  LocalDiscoveryBeaconManager, PairingQrBootstrapEngine, PairingTicket, PasskeyAlgorithmKind,
  PasskeyChallengeAuthenticator, PasskeyCredential

[POS]
Package facade for pairing.
"""

# ============================================================================
# Cross-Device Fast Pairing & Passkey Gateway Package (Item 160)
# ============================================================================

from .fast_pairing_gateway import (
    DeviceAuthVault,
    LocalDiscoveryBeaconManager,
    PairingQrBootstrapEngine,
    PasskeyChallengeAuthenticator,
)
from .pairing_types import (
    AuthChallenge,
    ChallengeResponse,
    DeviceTrustState,
    DiscoveredServiceBeacon,
    PairingTicket,
    PasskeyAlgorithmKind,
    PasskeyCredential,
)

__all__ = [
    "AuthChallenge",
    "ChallengeResponse",
    "DeviceAuthVault",
    "DeviceTrustState",
    "DiscoveredServiceBeacon",
    "LocalDiscoveryBeaconManager",
    "PairingQrBootstrapEngine",
    "PairingTicket",
    "PasskeyAlgorithmKind",
    "PasskeyChallengeAuthenticator",
    "PasskeyCredential",
]
