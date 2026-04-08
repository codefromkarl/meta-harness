#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_ROOT="${1:-${REPO_ROOT}/.demo-output}"

RUNS_ROOT="${OUTPUT_ROOT}/runs"
CANDIDATES_ROOT="${OUTPUT_ROOT}/candidates"
PROPOSALS_ROOT="${OUTPUT_ROOT}/proposals"
DATASETS_ROOT="${OUTPUT_ROOT}/datasets"
REPORTS_ROOT="${OUTPUT_ROOT}/reports"
BENCHMARK_CANDIDATES_ROOT="${OUTPUT_ROOT}/benchmark-candidates"

mkdir -p "${OUTPUT_ROOT}"

run_cli() {
  PYTHONPATH="${REPO_ROOT}/src" python -m meta_harness.cli "$@"
}

RUN_ID="$(run_cli run init \
  --profile demo_public \
  --project demo_public \
  --config-root "${REPO_ROOT}/configs" \
  --runs-root "${RUNS_ROOT}")"

run_cli run execute \
  --run-id "${RUN_ID}" \
  --task-set "${REPO_ROOT}/task_sets/demo/failure_repair.json" \
  --runs-root "${RUNS_ROOT}" >/dev/null

PROPOSAL_ID="$(run_cli optimize propose \
  --profile demo_public \
  --project demo_public \
  --config-root "${REPO_ROOT}/configs" \
  --runs-root "${RUNS_ROOT}" \
  --candidates-root "${CANDIDATES_ROOT}" \
  --proposals-root "${PROPOSALS_ROOT}" \
  --proposal-only)"

MATERIALIZED_CANDIDATE_ID="$(run_cli optimize materialize-proposal \
  --proposal-id "${PROPOSAL_ID}" \
  --proposals-root "${PROPOSALS_ROOT}" \
  --candidates-root "${CANDIDATES_ROOT}" \
  --config-root "${REPO_ROOT}/configs")"

run_cli dataset build-task-set \
  --task-set "${REPO_ROOT}/task_sets/demo/failure_repair.json" \
  --dataset-id demo-public-cases \
  --version v1 \
  --output "${DATASETS_ROOT}/demo-public-cases/v1/dataset.json" >/dev/null

run_cli dataset ingest-annotations \
  --dataset "${DATASETS_ROOT}/demo-public-cases/v1/dataset.json" \
  --annotations "${REPO_ROOT}/demo/annotations/demo_dataset_annotations.jsonl" \
  --output "${DATASETS_ROOT}/demo-public-cases/v2/dataset.json" >/dev/null

run_cli dataset derive-split \
  --dataset "${DATASETS_ROOT}/demo-public-cases/v2/dataset.json" \
  --split hard_case \
  --dataset-id demo-public-cases-hard \
  --version v1 \
  --output "${DATASETS_ROOT}/demo-public-cases-hard/v1/dataset.json" >/dev/null

run_cli dataset promote \
  --datasets-root "${DATASETS_ROOT}" \
  --dataset-id demo-public-cases-hard \
  --version v1 \
  --split hard_case \
  --promoted-by demo-user \
  --reason "public demo promotion" >/dev/null

run_cli run export-trace \
  --run-id "${RUN_ID}" \
  --runs-root "${RUNS_ROOT}" \
  --output "${OUTPUT_ROOT}/exports/${RUN_ID}.otel.json" >/dev/null

LOOP_ID="$(run_cli optimize loop \
  --profile demo_public \
  --project demo_public \
  --task-set "${REPO_ROOT}/task_sets/demo/failure_repair.json" \
  --config-root "${REPO_ROOT}/configs" \
  --runs-root "${RUNS_ROOT}" \
  --candidates-root "${CANDIDATES_ROOT}" \
  --proposals-root "${PROPOSALS_ROOT}" \
  --reports-root "${REPORTS_ROOT}" \
  --max-iterations 1)"

run_cli observe benchmark \
  --profile demo_public \
  --project demo_public \
  --task-set "${REPO_ROOT}/task_sets/demo/failure_repair.json" \
  --spec "${REPO_ROOT}/configs/benchmarks/demo_public_budget_headroom.json" \
  --config-root "${REPO_ROOT}/configs" \
  --runs-root "${RUNS_ROOT}" \
  --candidates-root "${BENCHMARK_CANDIDATES_ROOT}" \
  --reports-root "${REPORTS_ROOT}" \
  --no-auto-compact-runs >/dev/null

VALIDATION_REPORT="${REPORTS_ROOT}/demo_public_validation.json"
PYTHONPATH="${REPO_ROOT}/src" python -m meta_harness.artifact_contracts \
  --artifact "proposal=${PROPOSALS_ROOT}/${PROPOSAL_ID}" \
  --artifact "dataset=${DATASETS_ROOT}/demo-public-cases-hard/v1" \
  --artifact "loop=${REPORTS_ROOT}/loops/${LOOP_ID}" \
  --artifact "evaluator=${RUNS_ROOT}/${RUN_ID}/evaluators/command.json" \
  > "${VALIDATION_REPORT}"

cat <<EOF
demo_root=${OUTPUT_ROOT}
run_id=${RUN_ID}
proposal_id=${PROPOSAL_ID}
materialized_candidate_id=${MATERIALIZED_CANDIDATE_ID}
proposal_dir=${PROPOSALS_ROOT}/${PROPOSAL_ID}
dataset_dir=${DATASETS_ROOT}/demo-public-cases
trace_export=${OUTPUT_ROOT}/exports/${RUN_ID}.otel.json
loop_id=${LOOP_ID}
benchmark_report=${REPORTS_ROOT}/benchmarks/demo_public_budget_headroom.json
validation_report=${VALIDATION_REPORT}
EOF
