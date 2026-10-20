# clean_code_pipeline/

## Overview
Clean Code Assembly Pipeline & Architecture Dependency Linter package (Item 62).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Clean Code Assembly Pipeline & Architecture Dependency Linter package (Item 62). | — |
| `arch_dependency_linter.py` | Core | Static Architecture Dependency Linter and DIP Auto-Refactoring Advisor (Item 62). — LinterResult with detected ArchitectureViolation instances and DIP refactoring guidance. | ✅ |
| `pipeline_engine.py` | Core | Five-Stage Clean Code Multi-Agent Assembly Pipeline Engine (Item 62). — CleanCodeTask state transitions across the 5 stages (Specifier -> Coder -> Cleaner -> Hardener -> QA).; Gate-checked artifacts and pipeline completion records. | ✅ |
| `types.py` | Types | Data types for Clean Code Assembly Pipeline and Architecture Dependency Linter (Item 62). — PipelineStage, StageStatus, ViolationType, StageArtifact, | ✅ |
