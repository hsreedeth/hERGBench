#!/usr/bin/env bash
# 02_generate_configs.sh — Generate ChEMBL Stage 2 configs and verify TDC configs.
#
# Idempotent: running twice produces the same configs.
#
# Run from repo root:
#   bash scripts/runpod_stage2/02_generate_configs.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

VENV_DIR="${VENV_DIR:-/workspace/hERGBench/.venv}"
if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
fi

echo "=== 02 Generate Stage 2 Configs ==="

# ChEMBL configs (3 splits × 5 seeds = 15 files)
echo "  Generating ChEMBL configs..."
python src/make_chembl_stage2_configs.py

CHEMBL_COUNT=$(ls configs/chembl_stage2_multiseed/*.yaml 2>/dev/null | wc -l | tr -d ' ')
echo "  ChEMBL configs: ${CHEMBL_COUNT}/15"
if [[ "${CHEMBL_COUNT}" -ne 15 ]]; then
    echo "ERROR: expected 15 ChEMBL configs, found ${CHEMBL_COUNT}" >&2
    exit 1
fi

# TDC configs — verify all 15 already exist
TDC_COUNT=$(ls configs/stage2_multiseed/*.yaml 2>/dev/null | wc -l | tr -d ' ')
echo "  TDC configs:    ${TDC_COUNT}/15"
if [[ "${TDC_COUNT}" -ne 15 ]]; then
    echo "ERROR: expected 15 TDC configs in configs/stage2_multiseed/, found ${TDC_COUNT}." >&2
    echo "       Re-run: python src/make_stage2_multiseed_configs.py" >&2
    exit 1
fi

echo ""
echo "=== 02 Config generation complete ==="
echo "  TDC:    configs/stage2_multiseed/"
echo "  ChEMBL: configs/chembl_stage2_multiseed/"
