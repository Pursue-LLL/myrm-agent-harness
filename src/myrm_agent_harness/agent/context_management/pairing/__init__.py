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
