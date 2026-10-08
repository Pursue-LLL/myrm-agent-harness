"""MITRE ATT&CK TTP tagger and dual-use skill classifier.

Scans skill definitions, descriptions, and command signatures to assign tactical
MITRE ATT&CK tags and enforce quarantine and HITL policies.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re

from .types import (
    MitreAttackTactic,
    SkillSensitivityLevel,
    SkillTtpTagSpec,
)

# Tactical signature pattern tables mapping to MITRE ATT&CK tactics
_TACTIC_PATTERNS: dict[MitreAttackTactic, re.Pattern[str]] = {
    MitreAttackTactic.CREDENTIAL_ACCESS: re.compile(
        r"(?i)(mimikatz|lsass|procdump|dump_creds|hashdump|sam_dump|id_rsa|\.aws/credentials|keychain|ntds\.dit)"
    ),
    MitreAttackTactic.PRIVILEGE_ESCALATION: re.compile(
        r"(?i)(uac_bypass|sudo_escalate|dirtycow|token_impersonation|getsystem|cve-\d{4}-\d+|kernel_exploit)"
    ),
    MitreAttackTactic.COMMAND_AND_CONTROL: re.compile(
        r"(?i)(c2_beacon|cobalt_strike|reverse_shell|bind_shell|meterpreter|dnscat|sliver|havoc)"
    ),
    MitreAttackTactic.LATERAL_MOVEMENT: re.compile(
        r"(?i)(psexec|wmi_exec|smb_relay|pass_the_hash|pth|remote_service_create|winrm_exec)"
    ),
    MitreAttackTactic.DISCOVERY: re.compile(
        r"(?i)(nmap|masscan|bloodhound|sharphound|net_view|port_scanner|subdomain_enum)"
    ),
    MitreAttackTactic.EXFILTRATION: re.compile(
        r"(?i)(exfil_dns|exfil_http|curl_upload|data_staging|mega_uploader|stego_extract)"
    ),
}

_OFFENSIVE_CATEGORY_PATTERN = re.compile(
    r"(?i)(red_team|offensive|exploit|penetration_test|pentest|post_exploitation|reconnaissance)"
)


class DualUseTtpTagger:
    """Classifies skills by MITRE ATT&CK tactics and dual-use sensitivity."""

    def evaluate_skill(
        self,
        skill_name: str,
        description: str = "",
        command_signatures: list[str] | None = None,
    ) -> SkillTtpTagSpec:
        """Evaluate skill content and return TTP classification spec."""
        combined_text = f"{skill_name} {description} {' '.join(command_signatures or [])}"
        identified_tactics: list[MitreAttackTactic] = []
        identified_signatures: list[str] = []

        for tactic, pattern in _TACTIC_PATTERNS.items():
            matches = pattern.findall(combined_text)
            if matches:
                identified_tactics.append(tactic)
                identified_signatures.extend([str(m) for m in matches])

        is_offensive_category = bool(_OFFENSIVE_CATEGORY_PATTERN.search(combined_text))

        # Determine sensitivity level
        if identified_tactics or is_offensive_category:
            sensitivity = SkillSensitivityLevel.DUAL_USE_SENSITIVE
            requires_hitl = True
            quarantine_pod = True
        else:
            sensitivity = SkillSensitivityLevel.BENIGN
            requires_hitl = False
            quarantine_pod = False

        return SkillTtpTagSpec(
            skill_name=skill_name,
            tactics=identified_tactics,
            sensitivity_level=sensitivity,
            requires_hitl_approval=requires_hitl,
            quarantine_pod_enforced=quarantine_pod,
            description=description,
            identified_signatures=sorted(set(identified_signatures)),
        )
