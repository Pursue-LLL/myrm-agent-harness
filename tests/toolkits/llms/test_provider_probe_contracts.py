"""Unit tests for Provider Balance Probe data contracts and protocol.

[INPUT]
- myrm_agent_harness.toolkits.llms.probe::ProviderBalanceProbeProtocol, ProviderBalanceResult, ProviderBalanceStatus

[OUTPUT]
- test_provider_balance_result_to_dict
- test_provider_balance_probe_protocol_conformance

[POS]
Unit tests validating zero-prompt provider balance contracts.
"""

from myrm_agent_harness.toolkits.llms.probe import (
    ProviderBalanceProbeProtocol,
    ProviderBalanceResult,
    ProviderBalanceStatus,
)


def test_provider_balance_result_to_dict() -> None:
    res = ProviderBalanceResult(
        provider_id="deepseek",
        balance=42.50,
        currency="CNY",
        status=ProviderBalanceStatus.HEALTHY,
        is_estimated=False,
        details="DeepSeek cash balance: 42.50 CNY",
    )
    d = res.to_dict()
    assert d["provider_id"] == "deepseek"
    assert d["balance"] == 42.50
    assert d["currency"] == "CNY"
    assert d["status"] == "healthy"
    assert d["is_estimated"] is False
    assert d["details"] == "DeepSeek cash balance: 42.50 CNY"
    assert isinstance(d["updated_at"], str) and len(d["updated_at"]) > 0


def test_provider_balance_probe_protocol_conformance() -> None:
    class DummyProbe:
        @property
        def supported_provider_ids(self) -> frozenset[str]:
            return frozenset({"dummy"})

        async def probe(
            self,
            provider_id: str,
            api_key: str | None = None,
            api_base: str | None = None,
        ) -> ProviderBalanceResult:
            return ProviderBalanceResult(
                provider_id=provider_id,
                balance=100.0,
                currency="USD",
                status=ProviderBalanceStatus.HEALTHY,
            )

    probe_instance = DummyProbe()
    assert isinstance(probe_instance, ProviderBalanceProbeProtocol)
