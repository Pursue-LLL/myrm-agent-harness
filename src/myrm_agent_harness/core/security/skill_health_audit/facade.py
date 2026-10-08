"""
[POS] src/myrm_agent_harness/core/security/skill_health_audit/facade.py
[INPUT] hashlib, yaml, typing, types, ast_taint_engine, sarif_exporter, intel_provider
[OUTPUT] ConversationalSkillHealthAuditFacade
Unified facade for conversational skill health audit, taint assertion, and SARIF reporting.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import logging

import yaml

from .ast_taint_engine import SkillTaintSentinelEngine
from .intel_provider import PrivacyMinIntelProvider
from .sarif_exporter import Sarif210Exporter
from .types import (
    ExternalRequestDeclaration,
    FourRowHealthCard,
    IntelLookupStatus,
    SkillHealthAuditVerdict,
    SkillSecurityMetadata,
    TaintSeverity,
)

logger = logging.getLogger(__name__)


class ConversationalSkillHealthAuditFacade:
    """Unified entrypoint for in-chat skill health audits and undeclared exfiltration taint checks."""

    def __init__(
        self,
        taint_engine: SkillTaintSentinelEngine | None = None,
        intel_provider: PrivacyMinIntelProvider | None = None,
        sarif_exporter: Sarif210Exporter | None = None,
    ) -> None:
        self._taint_engine = taint_engine or SkillTaintSentinelEngine()
        self._intel_provider = intel_provider or PrivacyMinIntelProvider()
        self._sarif_exporter = sarif_exporter or Sarif210Exporter()

    @staticmethod
    def _parse_frontmatter(
        skill_name: str,
        frontmatter_str: str | None,
    ) -> SkillSecurityMetadata:
        """Parse declarative frontmatter YAML into SkillSecurityMetadata."""
        if not frontmatter_str or not frontmatter_str.strip():
            return SkillSecurityMetadata(skill_name=skill_name)

        try:
            # Strip markdown frontmatter delimiters if present
            cleaned = frontmatter_str.strip()
            if cleaned.startswith("---"):
                parts = cleaned.split("---", 2)
                cleaned = parts[1] if len(parts) > 1 else cleaned

            parsed = yaml.safe_load(cleaned)
            if not isinstance(parsed, dict):
                return SkillSecurityMetadata(skill_name=skill_name)

            publisher = str(parsed.get("publisher", "unknown"))
            official_repo = str(parsed["official_repo"]) if "official_repo" in parsed else None
            live_probe = str(parsed["live_probe"]) if "live_probe" in parsed else None
            binary_caution = str(parsed["binary_caution"]) if "binary_caution" in parsed else None

            # Parse external_requests list
            raw_ext = parsed.get("external_requests")
            ext_reqs: list[ExternalRequestDeclaration] = []
            if isinstance(raw_ext, list):
                for item in raw_ext:
                    if isinstance(item, dict) and "url" in item:
                        data_sent = tuple(
                            str(x) for x in item.get("data_sent", []) if isinstance(item.get("data_sent"), list)
                        )
                        ext_reqs.append(
                            ExternalRequestDeclaration(
                                url=str(item.get("url", "")),
                                purpose=str(item.get("purpose", "")),
                                data_sent=data_sent,
                                failure_mode=str(item.get("failure_mode", "graceful_degradation")),
                            )
                        )

            # Parse env_vars list
            raw_envs = parsed.get("env_vars")
            env_vars: tuple[str, ...] = (
                tuple(str(x) for x in raw_envs) if isinstance(raw_envs, list) else ()
            )

            return SkillSecurityMetadata(
                skill_name=str(parsed.get("name", skill_name)),
                publisher=publisher,
                official_repo=official_repo,
                external_requests=tuple(ext_reqs),
                env_vars=env_vars,
                live_probe_command=live_probe,
                binary_caution=binary_caution,
            )
        except Exception as e:
            logger.warning("Failed to parse skill frontmatter for %s: %s", skill_name, e)
            return SkillSecurityMetadata(skill_name=skill_name)

    def audit_skill(
        self,
        skill_name: str,
        code: str,
        frontmatter_str: str | None = None,
    ) -> SkillHealthAuditVerdict:
        """Execute in-chat security health audit and produce four-row card and SARIF."""
        content_hash = hashlib.sha256(code.encode()).hexdigest()
        metadata = self._parse_frontmatter(skill_name, frontmatter_str)

        # 1. AST Taint & undeclared sink analysis
        findings, dangerous_syscalls_count = self._taint_engine.analyze_source_code(
            code=code,
            metadata=metadata,
        )

        # 2. Privacy-minimized threat intel lookup
        intel_status = self._intel_provider.lookup_skill_intel(
            skill_name=skill_name,
            content_sha256=content_hash,
        )

        # 3. Calculate health score (0 - 100)
        score = 100
        undeclared_sinks = 0
        has_critical = False

        if intel_status == IntelLookupStatus.KNOWN_MALICIOUS:
            score -= 60

        for f in findings:
            if not f.is_declared and f.severity == TaintSeverity.CRITICAL_BLOCK:
                score -= 50
                undeclared_sinks += 1
                has_critical = True
            elif not f.is_declared and f.severity == TaintSeverity.HIGH:
                score -= 25
                undeclared_sinks += 1
            elif f.severity == TaintSeverity.WARNING:
                score -= 10

        score = max(0, score)
        is_clean = score >= 90 and not has_critical
        requires_attention = score < 90 or has_critical or dangerous_syscalls_count > 0

        # 4. Generate plain-language 4-row health card
        # Row 1: Source credibility
        if metadata.publisher in ("Tencent Zhuque Lab", "Myrm Official", "Anthropic", "Google"):
            credibility = f"官方认证 ({metadata.publisher})"
        elif metadata.official_repo:
            credibility = f"已知知名仓库 ({metadata.official_repo})"
        else:
            credibility = "第三方未知来源"

        # Row 2: File boundary
        if "open" in code or "read_text" in code or "Path." in code:
            file_boundary = "工作区文件操作 (需留意)"
        else:
            file_boundary = "仅限内部内存计算 (零越界)"

        # Row 3: Network egress
        if undeclared_sinks > 0:
            network_egress = "疑似隐蔽外泄 (未声明出站端点)"
        elif metadata.external_requests:
            network_egress = f"仅声明端点 ({len(metadata.external_requests)} 个受控地址)"
        else:
            network_egress = "零网络外发 (纯离线)"

        # Row 4: Dangerous syscalls
        if dangerous_syscalls_count > 0:
            syscall_desc = f"检测到 {dangerous_syscalls_count} 处系统命令调用"
        else:
            syscall_desc = "零危险底层调用"

        plain_card = FourRowHealthCard(
            source_credibility=credibility,
            file_boundary=file_boundary,
            network_egress=network_egress,
            dangerous_syscalls=syscall_desc,
        )

        # 5. Formulate anti-injection actionable advice
        if is_clean:
            advice = "该技能经 AST 静态审计与哈希情报校验通过，可放心加载至当前会话。"
        elif has_critical:
            advice = "发现敏感数据源直通未声明网络端点，建议暂停安装并核查技能源码出处。"
        else:
            advice = "建议在 frontmatter 中明确补充 external_requests 声明，或更新至作者最新版本。"

        # 6. Generate SARIF report
        raw_sarif = self._sarif_exporter.export_sarif(skill_name, findings)

        return SkillHealthAuditVerdict(
            skill_name=skill_name,
            content_sha256=content_hash,
            health_score=score,
            is_clean=is_clean,
            requires_attention=requires_attention,
            intel_status=intel_status,
            plain_language_card=plain_card,
            taint_findings=findings,
            declared_requests_count=len(metadata.external_requests),
            undeclared_sinks_count=undeclared_sinks,
            actionable_advice=advice,
            raw_sarif=raw_sarif,
        )
