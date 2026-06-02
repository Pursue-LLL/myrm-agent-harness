# Architecture Boundary Enforcement

Automated system to protect framework-business separation using whitelist-first approach with comprehensive import detection.

## Quick Start

```bash
# Full scan (CI mode)
python scripts/boundary_check.py

# Incremental scan (pre-commit mode, only changed files)
python scripts/boundary_check.py --incremental

# Auto-fix violations
python scripts/boundary_check.py --fix
```

## How It Works

**Boundary Rule**: Framework layer (`src/myrm_agent_harness/`) must only import from allowed framework modules.

**Detection Strategy**:
- **Whitelist Mode**: Only `myrm_agent_harness` is allowed (default-deny)
- **Static Imports**: `import x`, `from x import y`
- **Dynamic Imports**: `importlib.import_module()`, `__import__()`
- **Exec/Eval Detection**: `exec("import x")`, `eval("__import__('x')")`
- **F-string Detection**: `importlib.import_module(f"app.{name}")`
- **AST Analysis**: Detects both explicit and dynamic imports

**Enforcement Layers**:
1. **Local**: Pre-commit hook with incremental scanning (only changed files)
2. **CI**: GitHub Actions full scan on pull requests
3. **Tests**: Pytest suite (34 tests) validates boundary integrity
4. **Performance**: CI regression detection prevents performance degradation

**Error Reporting**:
- Priority classification: HIGH (core framework) / MEDIUM (infrastructure) / LOW (test/benchmarks)
- Statistics summary with per-priority breakdown
- Fix suggestions with dependency injection and Protocol examples

## Configuration

Edit `scripts/boundary_config.py` to modify rules:

```python
# Framework modules (whitelist - primary)
ALLOWED_FRAMEWORK_PREFIXES = (
    "myrm_agent_harness",
)

# Known business modules (blacklist - documentation)
BANNED_PREFIXES = (
    "myrm_agent_server",
    "myrm_control_plane",
    "app",
)

# Allowed cross-layer paths (path whitelist)
ALLOWED_PATHS = (
    "tests/integration",
    "tests/e2e",
    "benchmarks",
)
```

## Fixing Violations

### Option 1: Auto-Fix (Recommended)

```bash
python scripts/boundary_check.py --fix
git diff  # Review changes
git add .
git commit
```

### Option 2: Manual Fix

**Strategy 1** - Move to framework layer:
```python
# If the imported module is generic/reusable logic
# Move it to src/myrm_agent_harness/
```

**Strategy 2** - Dependency injection:
```python
from typing import Protocol

class DatabaseProtocol(Protocol):
    def get_session(self): ...

def your_function(db: DatabaseProtocol):
    session = db.get_session()
```

## Installation

Pre-commit hook setup (automatically blocks violations):

```bash
pip install pre-commit
pre-commit install
```

## Performance

Based on `benchmarks/bench_boundary_detection.py`:
- Full scan: 1.68 seconds for 626 files (3875 imports)
- Import matching: 0.48 μs per check (2.09M checks/sec)
- Incremental scan: <0.1 seconds (only changed files)
- Auto-fix: Instant (comments out violations)

Performance regression detection:
```bash
# Save baseline
python benchmarks/bench_boundary_detection.py --save-baseline benchmarks/baseline_boundary.json

# Check for regression (30% tolerance)
python benchmarks/bench_boundary_detection.py --check-regression benchmarks/baseline_boundary.json
```

## Architecture

See [ARCHITECTURE.md](../ARCHITECTURE.md) for framework design principles.
