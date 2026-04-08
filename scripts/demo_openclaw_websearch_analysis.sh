#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_ROOT="${1:-${REPO_ROOT}/.openclaw-demo-output}"

"${REPO_ROOT}/scripts/bootstrap.sh" --require-openclaw >/dev/null

# shellcheck disable=SC1090
source "${REPO_ROOT}/.venv/bin/activate"

RUNS_ROOT="${OUTPUT_ROOT}/runs"
CANDIDATES_ROOT="${OUTPUT_ROOT}/candidates"
REPORTS_ROOT="${OUTPUT_ROOT}/reports"
EXPORTS_ROOT="${OUTPUT_ROOT}/exports"

mkdir -p "${OUTPUT_ROOT}" "${RUNS_ROOT}" "${CANDIDATES_ROOT}" "${REPORTS_ROOT}" "${EXPORTS_ROOT}"

BENCHMARK_JSON="${OUTPUT_ROOT}/benchmark-result.json"

PYTHONPATH="${REPO_ROOT}/src" python -m meta_harness.cli observe benchmark \
  --profile demo_openclaw \
  --project demo_openclaw \
  --config-root "${REPO_ROOT}/configs" \
  --runs-root "${RUNS_ROOT}" \
  --candidates-root "${CANDIDATES_ROOT}" \
  --reports-root "${REPORTS_ROOT}" \
  --task-set "${REPO_ROOT}/task_sets/demo/openclaw_websearch_analysis.json" \
  --spec "${REPO_ROOT}/configs/benchmarks/demo_openclaw_websearch_analysis.json" \
  --focus retrieval >"${BENCHMARK_JSON}"

BEST_RUN_ID="$(python - "${BENCHMARK_JSON}" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
best_variant = payload.get("best_variant")
for item in payload.get("variants", []):
    if item.get("name") == best_variant:
        print(item.get("run_id", ""))
        break
PY
)"

if [[ -n "${BEST_RUN_ID}" ]]; then
  PYTHONPATH="${REPO_ROOT}/src" python -m meta_harness.cli run export-trace \
    --run-id "${BEST_RUN_ID}" \
    --runs-root "${RUNS_ROOT}" \
    --output "${EXPORTS_ROOT}/${BEST_RUN_ID}.otel.json" >/dev/null
fi

cat <<EOF
demo_root=${OUTPUT_ROOT}
benchmark_result=${BENCHMARK_JSON}
best_run_id=${BEST_RUN_ID}
trace_export=${EXPORTS_ROOT}/${BEST_RUN_ID}.otel.json
EOF
