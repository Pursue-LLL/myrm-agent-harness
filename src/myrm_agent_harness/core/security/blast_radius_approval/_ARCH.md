# blast_radius_approval/

## Overview

Approval Card Blast Radius Dry-Run Impact Preview & Typed Launch Codes Suite. src/myrm_agent_harness/core/security/blast_radius_approval/__init__.py Approval Card Blast Radius Dry-Run Impact Preview & Typed Launch Codes Suite. Exports domain types, dry-run engine, launch code manager, span grouper, and facade. Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Approval Card Blast Radius Dry-Run Impact Preview & Typed Launch Codes Suite — src/myrm_agent_harness/core/security/blast_radius_approval/__init__.py Approval Card Blast Radius Dry-Run Impact Preview & Typed Launch Codes Suite. Exports domain types, dry-run engine, launch code manager, span grouper, and facade. Strict typing applied: No `Any` types allowed. | ✅ |
| dry_run_probe.py | Core | Pre-execution dry-run impact enumeration engine for destructive commands — src/myrm_agent_harness/core/security/blast_radius_approval/dry_run_probe.py [INPUT] time, glob, re, typing, types [OUTPUT] DryRunProbeEngine Pre-execution dry-run impact enumeration engine for destructive commands. Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified facade for blast radius dry-run impact preview, typed launch codes, and never-fold batch grouping — src/myrm_agent_harness/core/security/blast_radius_approval/facade.py [INPUT] typing, types, dry_run_probe, launch_code_manager, span_grouper [OUTPUT] BlastRadiusApprovalFacade Unified facade for blast radius dry-run impact preview, typed launch codes, and never-fold batch grouping. Strict typing applied: No `Any` types allowed. | ✅ |
| launch_code_manager.py | Core | Typed one-time challenge codes for high-risk irreversible actions — src/myrm_agent_harness/core/security/blast_radius_approval/launch_code_manager.py [INPUT] time, secrets, typing, types [OUTPUT] TypedLaunchCodeManager Typed one-time challenge codes for high-risk irreversible actions. Strict typing applied: No `Any` types allowed. | ✅ |
| span_grouper.py | Core | Batch approval span grouper preventing destructive commands from being folded into common groups — src/myrm_agent_harness/core/security/blast_radius_approval/span_grouper.py [INPUT] typing, types, dry_run_probe, launch_code_manager [OUTPUT] NeverFoldSpanGrouper Batch approval span grouper preventing destructive commands from being folded into common groups. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Domain types for Blast Radius Dry-Run Impact Preview & Typed Launch Codes Suite — src/myrm_agent_harness/core/security/blast_radius_approval/types.py [INPUT] dataclasses, enum, typing [OUTPUT] ImpactTargetType, ImpactPreviewTarget, DryRunImpactPreview, LaunchCodeRequirement, ApprovalSpanGroupPolicy Domain types for Blast Radius Dry-Run Impact Preview & Typed Launch Codes Suite. Strict typing applied: No `Any` types allowed. | ✅ |
