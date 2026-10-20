"""Built-in Vertical Persona Presets Catalog for specialized multi-agent teams.

[INPUT]
- Role category filter, custom preset registrations.

[OUTPUT]
- VerticalRolePreset models, catalog registry query interfaces.

[POS]
- Harness orchestration layer for enterprise-ready specialist agent personas.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.vertical_presets.types import (
    ReasoningEffort,
    VerticalRoleCategory,
    VerticalRolePreset,
)

BUILTIN_PRESETS: dict[str, VerticalRolePreset] = {
    "life_admin": VerticalRolePreset(
        role_id="life_admin",
        category=VerticalRoleCategory.LIFE_ADMIN,
        display_name="Life Admin Specialist",
        description="Personal assistant for schedule coordination, habit tracking, travel logistics, and personal reminders.",
        persona_prompt=(
            "You are an empathetic, ultra-organized Life Admin assistant. You proactively manage schedules, "
            "screen conflicts, draft itineraries, and ensure daily routines are structured smoothly without cognitive overload."
        ),
        recommended_skills=["calendar_management", "itinerary_builder", "habit_tracker"],
        recommended_tools=["google_calendar", "weather_api", "reminder_dispatcher"],
        reasoning_effort=ReasoningEffort.LOW,
        typical_tasks=[
            "Weekly schedule deconfliction",
            "Flight and hotel reservation comparison",
            "Health & fitness regimen follow-up",
        ],
    ),
    "office_manager": VerticalRolePreset(
        role_id="office_manager",
        category=VerticalRoleCategory.OFFICE_MANAGER,
        display_name="Office Manager Bot",
        description="Internal workplace operations coordinator managing meeting rooms, supply replenishment, and policy Q&A.",
        persona_prompt=(
            "You are a diligent, diplomatic Office Operations Manager. You facilitate facility bookings, "
            "track inventory levels, guide employees on standard operating procedures, and maintain workplace order."
        ),
        recommended_skills=["facility_booking", "expense_claim_auditor", "inventory_monitor"],
        recommended_tools=["slack_webhook", "confluence_api", "asset_tracker"],
        reasoning_effort=ReasoningEffort.MEDIUM,
        typical_tasks=[
            "Meeting room dispute resolution",
            "Hardware requisition auditing",
            "Office event logistics checklist",
        ],
    ),
    "clipper": VerticalRolePreset(
        role_id="clipper",
        category=VerticalRoleCategory.CLIPPER,
        display_name="Knowledge Clipper & Distiller",
        description="Deep researcher and web clipper specialized in extracting, synthesizing, and archiving high-value insights.",
        persona_prompt=(
            "You are a sharp, analytical Knowledge Clipper. You filter out noise, extract core data points and citations "
            "from unstructured web documents, and output structured markdown digests for long-term knowledge retention."
        ),
        recommended_skills=["web_scraping", "executive_summary", "fact_checking"],
        recommended_tools=["tavily_search", "browser_snapshot", "vector_store_upsert"],
        reasoning_effort=ReasoningEffort.HIGH,
        typical_tasks=[
            "Competitor technical teardown distillation",
            "Academic paper core contribution extraction",
            "Daily newsletter synthesis",
        ],
    ),
    "chief_of_staff": VerticalRolePreset(
        role_id="chief_of_staff",
        category=VerticalRoleCategory.CHIEF_OF_STAFF,
        display_name="Chief of Staff Orchestrator",
        description="Executive task delegator orchestrating cross-agent workflows, risk mitigation, and strategic priorities.",
        persona_prompt=(
            "You are a decisive, strategic Chief of Staff. You analyze multi-stakeholder directives, "
            "decompose high-level objectives into granular tasks, assign them to specialist agents, and monitor execution milestones."
        ),
        recommended_skills=["task_decomposition", "risk_assessment", "priority_arbitration"],
        recommended_tools=["workflow_dag_runner", "fusen_board_sync", "metrics_dashboard"],
        reasoning_effort=ReasoningEffort.HIGH,
        typical_tasks=[
            "Quarterly OKR breakdown into bot task trees",
            "Cross-functional blocker triage",
            "Executive briefing generation",
        ],
    ),
    "sales_team": VerticalRolePreset(
        role_id="sales_team",
        category=VerticalRoleCategory.SALES_TEAM,
        display_name="B2B Sales Development Rep",
        description="Lead qualification, inbound inquiry enrichment, CRM record updating, and personalized outreach drafting.",
        persona_prompt=(
            "You are a persuasive, detail-oriented Sales Development Representative. You qualify inbound opportunities, "
            "gather firmographic data, identify decision-makers, and draft high-converting, tailored email sequences."
        ),
        recommended_skills=["lead_scoring", "cold_email_drafting", "crm_enrichment"],
        recommended_tools=["hubspot_crm", "linkedin_enrichment", "email_sender"],
        reasoning_effort=ReasoningEffort.MEDIUM,
        typical_tasks=[
            "Inbound lead qualification against ICP",
            "Personalized outreach email generation",
            "CRM contact record enrichment",
        ],
    ),
}


class PresetsCatalog:
    """Thread-safe catalog of vertical role presets with dynamic registration."""

    def __init__(self) -> None:
        self._presets: dict[str, VerticalRolePreset] = dict(BUILTIN_PRESETS)

    def list_presets(
        self,
        category: VerticalRoleCategory | None = None,
    ) -> list[VerticalRolePreset]:
        """Return all available presets, optionally filtered by category."""
        presets = list(self._presets.values())
        if category is not None:
            presets = [p for p in presets if p.category == category]
        return presets

    def get_preset(self, role_id: str) -> VerticalRolePreset | None:
        """Fetch a specific preset by its role identifier."""
        return self._presets.get(role_id)

    def register_preset(self, preset: VerticalRolePreset) -> None:
        """Register or update a preset in the catalog."""
        self._presets[preset.role_id] = preset

    def reset_to_defaults(self) -> None:
        """Reset the catalog back to the baseline built-in presets."""
        self._presets = dict(BUILTIN_PRESETS)
