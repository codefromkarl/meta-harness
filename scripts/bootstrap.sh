#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${VENV_DIR:-${REPO_ROOT}/.venv}"
REQUIRE_OPENCLAW=0

if [[ "${1:-}" == "--require-openclaw" ]]; then
  REQUIRE_OPENCLAW=1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found in PATH" >&2
  exit 2
fi

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "${PYTHON_VERSION}" < "3.11" ]]; then
  echo "Python 3.11+ is required, current version: ${PYTHON_VERSION}" >&2
  exit 2
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install -e "${REPO_ROOT}[dev]" >/dev/null

if [[ "${REQUIRE_OPENCLAW}" == "1" ]]; then
  if ! command -v openclaw >/dev/null 2>&1; then
    echo "openclaw not found in PATH. Install OpenClaw before running the OpenClaw demo." >&2
    exit 3
  fi
  if ! openclaw agent --help >/dev/null 2>&1; then
    echo "openclaw agent is not available. Verify your OpenClaw CLI installation." >&2
    exit 3
  fi
fi

cat <<EOF
repo_root=${REPO_ROOT}
venv_dir=${VENV_DIR}
python_version=${PYTHON_VERSION}
openclaw_required=${REQUIRE_OPENCLAW}
EOF
