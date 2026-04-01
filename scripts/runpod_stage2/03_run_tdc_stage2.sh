#!/usr/bin/env bash
# 03_run_tdc_stage2.sh — Train all 15 TDC Stage 2 ChemProp configs.
#
# Configs: configs/stage2_multiseed/*.yaml  (3 splits × 5 torch seeds)
# Outputs: reports/stage2_multiseed_analysis/
#
# Environment variables:
#   SKIP_EXISTING  default: 1   (set 0 to force retrain)
#   GPU_ID         default: 0
#   VENV_DIR       auto-detected if unset

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
REPO_ROOT="$(stage2_repo_root)"
cd "${REPO_ROOT}"

activate_stage2_venv "${REPO_ROOT}" || true

SKIP_EXISTING="${SKIP_EXISTING:-1}"
GPU_ID="${GPU_ID:-0}"
CONFIG_DIR="configs/stage2_multiseed"
OUTPUT_DIR="reports/stage2_multiseed_analysis"

export HERGBENCH_ALLOW_GPU=1
export CUDA_VISIBLE_DEVICES="${GPU_ID}"

mkdir -p "${OUTPUT_DIR}" reports/runs

echo "=== 03 Run TDC Stage 2 ==="
echo "    CONFIG_DIR     = ${CONFIG_DIR}"
echo "    OUTPUT_DIR     = ${OUTPUT_DIR}"
echo "    SKIP_EXISTING  = ${SKIP_EXISTING}"
echo "    GPU_ID         = ${GPU_ID}"
echo ""

python - <<PYEOF
import logging

from hergbench.analysis.stage2_multiseed_runner import run_stage2_multiseed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")

skip_existing = "${SKIP_EXISTING}" == "1"

raw = run_stage2_multiseed(
    dataset="tdc",
    config_dir="${CONFIG_DIR}",
    output_dir="${OUTPUT_DIR}",
    skip_existing=skip_existing,
    allow_gpu=True,
)
print(f"\nCollected {len(raw)} AD-bin rows for TDC Stage 2.")
print(f"Raw results: ${OUTPUT_DIR}/stage2_ad_bins_raw.csv")
print(f"Manifest: ${OUTPUT_DIR}/stage2_run_manifest.csv")
PYEOF

echo ""
echo "=== 03 TDC Stage 2 complete ==="
