#!/usr/bin/env bash
# 02_run_multiseed.sh — Train XGBoost across all 5 seeds × 3 splits on ChEMBL.
#
# Run from repo root on the pod:
#   bash scripts/runpod_chembl/02_run_multiseed.sh
#
# Environment variables:
#   VENV_DIR       default: /workspace/hERGBench/.venv
#   OUTPUT_DIR     default: reports/chembl_multiseed_analysis
#   SKIP_EXISTING  default: 1   (set 0 to force retrain)
#   RANDOM_STATE   default: 42

set -euo pipefail

VENV_DIR="${VENV_DIR:-/workspace/hERGBench/.venv}"
OUTPUT_DIR="${OUTPUT_DIR:-reports/chembl_multiseed_analysis}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
RANDOM_STATE="${RANDOM_STATE:-42}"

# Activate venv
if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
else
    echo "ERROR: venv not found at ${VENV_DIR}. Run the bootstrap script first."
    exit 1
fi

RUNNER_ARGS=(
    "--dataset" "chembl"
    "--output-dir" "${OUTPUT_DIR}"
    "--random-state" "${RANDOM_STATE}"
)
if [[ "${SKIP_EXISTING}" == "0" ]]; then
    RUNNER_ARGS+=("--no-skip-existing")
fi

echo "=== 02 Running ChEMBL multi-seed benchmark ==="
echo "    OUTPUT_DIR     = ${OUTPUT_DIR}"
echo "    SKIP_EXISTING  = ${SKIP_EXISTING}"
echo "    RANDOM_STATE   = ${RANDOM_STATE}"
echo ""

python scripts/run_multiseed_stage1.py "${RUNNER_ARGS[@]}"

echo ""
echo "=== 02 Complete — raw results in ${OUTPUT_DIR}/ ==="
