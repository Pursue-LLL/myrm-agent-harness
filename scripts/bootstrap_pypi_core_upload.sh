#!/usr/bin/env bash
# One-time bootstrap: upload core platform wheels with a user PyPI API token.
# Trusted Publisher (OIDC) cannot create new PyPI projects; use this once per
# release line, then add Trusted Publishers on each core project page on PyPI.
#
# PyPI enforces a per-account quota on first-time project creation (429
# "Too many new projects created"). Stagger uploads by hours, or email
# admin@pypi.org with the blocked project names.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WHEEL_DIR=""
ONLY_PLATFORMS=""

usage() {
  echo "Usage: PYPI_API_TOKEN=... $0 [--only win32-arm64,win32-x64] <wheel-dir>" >&2
  echo "  wheel-dir: dir with core-wheel-*/ *.whl (e.g. .pypi-bootstrap)" >&2
  echo "  Or: gh run download <run-id> --repo Pursue-LLL/myrm-agent-harness \\" >&2
  echo "        --pattern 'core-wheel-*' -D /tmp/wheels" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --only)
      ONLY_PLATFORMS="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$WHEEL_DIR" ]]; then
        WHEEL_DIR="$1"
        shift
      else
        echo "ERROR: Unexpected argument: $1" >&2
        usage
        exit 1
      fi
      ;;
  esac
done

if [[ -z "${PYPI_API_TOKEN:-}" ]]; then
  echo "ERROR: Set PYPI_API_TOKEN (pypi.org → Account → API tokens)." >&2
  exit 1
fi

if [[ -z "$WHEEL_DIR" ]]; then
  usage
  exit 1
fi

mapfile -t wheels < <(find "$WHEEL_DIR" -path '*/core-wheel-*/*.whl' -o -path '*/core-wheel-*' -name '*.whl' 2>/dev/null | sort -u)
if [[ ${#wheels[@]} -eq 0 ]]; then
  mapfile -t wheels < <(find "$WHEEL_DIR" -name 'myrm_agent_harness_core_*.whl' | sort)
fi
if [[ ${#wheels[@]} -eq 0 ]]; then
  echo "ERROR: No core wheels under $WHEEL_DIR" >&2
  exit 1
fi

if [[ -n "$ONLY_PLATFORMS" ]]; then
  IFS=',' read -r -a platform_keys <<< "$ONLY_PLATFORMS"
  filtered=()
  for wheel in "${wheels[@]}"; do
    for key in "${platform_keys[@]}"; do
      key="${key// /}"
      if [[ "$wheel" == *"core-wheel-${key}/"* ]] || [[ "$wheel" == *"myrm_agent_harness_core_${key//-/_}-"* ]]; then
        filtered+=("$wheel")
        break
      fi
    done
  done
  wheels=("${filtered[@]}")
fi

if [[ ${#wheels[@]} -eq 0 ]]; then
  echo "ERROR: No wheels matched --only ${ONLY_PLATFORMS:-<empty>}" >&2
  exit 1
fi

echo "Uploading ${#wheels[@]} core wheel(s)..."
export TWINE_USERNAME=__token__
export TWINE_PASSWORD="${PYPI_API_TOKEN}"
uv tool run twine upload --non-interactive --skip-existing "${wheels[@]}"
echo "Done. Add Trusted Publishers on pypi.org for each core project name, then re-run tag publish."
