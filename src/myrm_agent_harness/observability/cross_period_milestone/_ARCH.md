# cross_period_milestone/

## Overview
Multi-Agent cross-period pivot reporting, per-runtime usage attribution, and gamified efficiency milestones suite.
Inspired by enterprise operational views from Web Agent platforms and DeepSeek-Bot usage analytics.
Provides cross-period comparative analysis (weekly/monthly/quarterly/custom) with period-over-period growth metrics, team adoption leaderboards, and gamified competency progression (levels, XP, daily missions, efficiency badges).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public re-exports of models and tracking engine. | ✅ |
| `models.py` | Domain Models | Pydantic data schemas for pivot reports, usage breakdowns, team metrics, and gamified milestones. | ✅ |
| `tracker.py` | Core Engine | CrossPeriodMilestoneEngine managing activity ingest, growth calculations, daily quests, and badges. | ✅ |
