# Domain-Specific Agent Job Description & Preference Compounding Suite Architecture

## 1. Problem Statement & Motivation
Across current AI agent ecosystems, creating an agent often degrades to an empty text prompt input box. This leads to the **"General Helper" Anti-Pattern**:
- Unclear scope, vague tools, and undefined authority boundaries.
- The agent doesn't know which actions it can take autonomously and which require human approval.
- Zero progressive asset accumulation: after running for months, the agent is no smarter or better aligned than day one, becoming an ephemeral toy rather than an indispensable digital colleague.

## 2. Core Architectural Pillars (Inspired by xAI Grok Bot Blueprints & Industry Insights)
- **4-Pillar Job Description Specification (`job_builder.py`)**:
  1. `target_scope`: Precise domain objective and scope (e.g. Talent Scout, Expense Manager, Bug Reproduction).
  2. `tools_and_sources`: Bound datasets, web sources, and dedicated tools.
  3. `work_style`: Tone and execution philosophy (rigorous, agile, concise).
  4. `approval_boundary`: Rigorous division between autonomous execution actions vs HITL escalation actions.
- **Domain Preference & Lesson Compounding Engine (`compounding_engine.py`)**:
  - Automatically captures structured domain rules (Positive Preferences, Negative Constraints, Inspection Lessons) from task feedback.
  - Persists and syncs rules directly into the agent's dedicated `~/.myrm/agents/<agent_id>/MEMORY.md` markdown file.
  - Injects compiled compounding rules monotonically on every prompt invocation.
- **Compounding Maturity Progression (`maturity_tracker.py`)**:
  - Evaluates rule volume, diversity, and adoption hits into a 0~100 maturity score.
  - Categorizes agents into developmental stages: Rookie ➔ Practitioner ➔ Specialist ➔ Partner.
