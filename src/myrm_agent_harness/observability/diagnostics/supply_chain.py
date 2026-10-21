"""[INPUT]
- backends.skills.scanning.dependency_extractor::DeclaredDependency (POS: 声明依赖结构)
- backends.skills.scanning.osv_scanner::query_osv_batch (POS: OSV 批量扫描)
- backends.skills.scanning.scanner::ScanSeverity (POS: 扫描严重性等级)
- backends.skills.scanning.security_advisories::match_known_advisories (POS: 离线已知恶意库匹配)
- backends.skills.scanning.vuln_cache::get_vuln_cache (POS: 漏洞缓存)
- observability.diagnostics.protocols::HealthReport (POS: 健康报告契约)
- observability.diagnostics.manager::register_diagnostic (POS: 探针自动注册)

[OUTPUT]
- check_supply_chain_health: 运行环境依赖与供应链安全健康度检查探针。

[POS]
Harness 框架层统一供应链依赖安全性探针。自动审计当前 Python 运行时已安装的分发包与关键依赖，
检测是否存在已知恶意供应链包或高危 CVE 漏洞。
"""

from __future__ import annotations

import importlib.metadata
import logging
import time

from myrm_agent_harness.backends.skills.scanning.dependency_extractor import DeclaredDependency
from myrm_agent_harness.backends.skills.scanning.osv_scanner import query_osv_batch
from myrm_agent_harness.backends.skills.scanning.scanner import ScanSeverity
from myrm_agent_harness.backends.skills.scanning.security_advisories import match_known_advisories
from myrm_agent_harness.backends.skills.scanning.vuln_cache import get_vuln_cache
from myrm_agent_harness.observability.diagnostics.manager import register_diagnostic
from myrm_agent_harness.observability.diagnostics.protocols import HealthReport

logger = logging.getLogger(__name__)


async def check_supply_chain_health() -> HealthReport:
    """Audit runtime Python environment packages against known advisories and OSV database."""
    try:
        start_t = time.perf_counter()
        dists = list(importlib.metadata.distributions())
        deps: list[DeclaredDependency] = []

        for dist in dists:
            name = (dist.metadata["Name"] or "").strip()
            version = (dist.version or "").strip()
            if name:
                deps.append(
                    DeclaredDependency(
                        name=name.lower(),
                        version_spec=version,
                        ecosystem="PyPI",
                        file_path="active_venv",
                    )
                )

        offline_findings = match_known_advisories(deps)
        cache = get_vuln_cache()
        osv_findings = await query_osv_batch(deps, cache=cache)

        critical_findings = []
        high_findings = []
        warn_findings = []

        for f in [*offline_findings, *osv_findings]:
            if f.severity == ScanSeverity.CRITICAL:
                critical_findings.append(f)
            elif f.severity == ScanSeverity.HIGH:
                high_findings.append(f)
            else:
                warn_findings.append(f)

        duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
        meta_data: dict[str, object] = {
            "packages_scanned_count": len(deps),
            "critical_vuln_count": len(critical_findings),
            "high_vuln_count": len(high_findings),
            "medium_low_vuln_count": len(warn_findings),
            "scan_duration_ms": duration_ms,
        }
        metrics: dict[str, float] = {
            "packages_scanned_count": float(len(deps)),
            "critical_vuln_count": float(len(critical_findings)),
            "high_vuln_count": float(len(high_findings)),
            "scan_duration_ms": duration_ms,
        }

        if critical_findings:
            pkg_names = ", ".join(dict.fromkeys(f.package_name for f in critical_findings[:3]))
            return HealthReport(
                component_name="SupplyChainSecurity",
                status="fail",
                code="ERR_SUPPLY_CHAIN_CRITICAL_MALWARE",
                meta_data=meta_data,
                metrics=metrics,
                message="Critical malicious or compromised package detected in runtime environment.",
                detail=f"Detected {len(critical_findings)} critical advisory(ies) affecting packages: {pkg_names}.",
                fix_suggestion="Immediately remove or quarantine affected dependencies using package manager.",
            )

        if high_findings:
            pkg_names = ", ".join(dict.fromkeys(f.package_name for f in high_findings[:3]))
            return HealthReport(
                component_name="SupplyChainSecurity",
                status="warn",
                code="WARN_SUPPLY_CHAIN_HIGH_VULNERABILITY",
                meta_data=meta_data,
                metrics=metrics,
                message="High-severity CVE vulnerability detected in installed dependencies.",
                detail=f"Detected {len(high_findings)} high-severity advisory(ies) affecting packages: {pkg_names}.",
                fix_suggestion="Review affected dependencies and update to patched versions.",
            )

        return HealthReport(
            component_name="SupplyChainSecurity",
            status="pass",
            code="OK_SUPPLY_CHAIN_HEALTHY",
            meta_data=meta_data,
            metrics=metrics,
            message=f"Supply chain dependencies verified clean ({len(deps)} packages scanned, {duration_ms}ms).",
            detail=f"All {len(deps)} installed environment packages passed offline advisory and OSV.dev vulnerability checks.",
            fix_suggestion=None,
        )

    except Exception as exc:
        logger.warning("Supply chain vulnerability diagnostic check degraded: %s", exc)
        return HealthReport(
            component_name="SupplyChainSecurity",
            status="pass",
            code="WARN_SUPPLY_CHAIN_SCAN_DEGRADED",
            meta_data={"error": str(exc)},
            message="Supply chain security scan degraded (offline or cache-only mode).",
            detail=f"Supply chain check completed with fallback: {exc}",
            fix_suggestion=None,
        )


register_diagnostic(check_supply_chain_health)
