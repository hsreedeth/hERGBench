#!/usr/bin/env bash
# 03_smoke_live_single_config.sh — Run one Stage 2 config with live ChemProp epoch logs.
#
# Usage:
#   bash scripts/runpod_stage2/03_smoke_live_single_config.sh
#   bash scripts/runpod_stage2/03_smoke_live_single_config.sh configs/stage2_multiseed/stage2_chemprop_random_seed11_torch33.yaml
#
# Environment variables:
#   CONFIG_PATH  optional alternative to positional arg
#   GPU_ID       default: 0
#   LOG_DIR      default: /workspace/stage2_live_logs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
REPO_ROOT="$(stage2_repo_root)"
cd "${REPO_ROOT}"

activate_stage2_venv "${REPO_ROOT}" || true

CONFIG_PATH="${1:-${CONFIG_PATH:-configs/chembl_stage2_multiseed/stage2_chemprop_chembl_random_seed11_torch42.yaml}}"
GPU_ID="${GPU_ID:-0}"
LOG_DIR="${LOG_DIR:-/workspace/stage2_live_logs}"

if [[ ! -f "${CONFIG_PATH}" ]]; then
    echo "ERROR: config not found: ${CONFIG_PATH}" >&2
    exit 1
fi

mkdir -p "${LOG_DIR}" reports/runs

CONFIG_STEM="$(basename "${CONFIG_PATH}" .yaml)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_PATH="${LOG_DIR}/${TIMESTAMP}_${CONFIG_STEM}.log"

export HERGBENCH_ALLOW_GPU=1
export HERGBENCH_STREAM_CHEMPROP=1
export CUDA_VISIBLE_DEVICES="${GPU_ID}"
export PYTHONUNBUFFERED=1

echo "=== 03 Smoke Test Stage 2 (Live Logs) ==="
echo "  CONFIG_PATH  = ${CONFIG_PATH}"
echo "  GPU_ID       = ${GPU_ID}"
echo "  LOG_PATH     = ${LOG_PATH}"
echo ""

python -u src/hergbench/stage2_pipeline.py --config "${CONFIG_PATH}" 2>&1 | tee "${LOG_PATH}"
status="${PIPESTATUS[0]}"

if [[ "${status}" -ne 0 ]]; then
    echo ""
    echo "Smoke test failed with status ${status}. Log: ${LOG_PATH}" >&2
    exit "${status}"
fi

RUN_DIR="$(ls -td reports/runs/*stage2_chemprop* 2>/dev/null | head -n 1 || true)"
if [[ -n "${RUN_DIR}" ]]; then
    echo ""
    echo "Latest run dir: ${RUN_DIR}"
fi

echo "Smoke test completed successfully. Log: ${LOG_PATH}"
