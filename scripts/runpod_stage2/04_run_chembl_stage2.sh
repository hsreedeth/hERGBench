#!/usr/bin/env bash
# 04_run_chembl_stage2.sh — Train all 15 ChEMBL Stage 2 ChemProp configs.
#
# Configs: configs/chembl_stage2_multiseed/*.yaml  (3 splits × 5 data seeds)
# Outputs: reports/chembl_stage2_multiseed_analysis/
#
# Environment variables:
#   SKIP_EXISTING  default: 1   (set 0 to force retrain)
#   GPU_ID         default: 0
#   VENV_DIR       default: /workspace/hERGBench/.venv

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

VENV_DIR="${VENV_DIR:-/workspace/hERGBench/.venv}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
GPU_ID="${GPU_ID:-0}"
CONFIG_DIR="configs/chembl_stage2_multiseed"
OUTPUT_DIR="reports/chembl_stage2_multiseed_analysis"
MANIFEST="${OUTPUT_DIR}/stage2_run_manifest.csv"

if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
fi

export HERGBENCH_ALLOW_GPU=1
export CUDA_VISIBLE_DEVICES="${GPU_ID}"

if [[ ! -d "${CONFIG_DIR}" ]]; then
    echo "ERROR: ${CONFIG_DIR} not found. Run 02_generate_configs.sh first." >&2
    exit 1
fi

mkdir -p "${OUTPUT_DIR}" reports/runs

CONFIGS=($(ls "${CONFIG_DIR}"/*.yaml | sort))
TOTAL=${#CONFIGS[@]}
echo "=== 04 Run ChEMBL Stage 2 (${TOTAL} configs) ==="
echo "    SKIP_EXISTING = ${SKIP_EXISTING}"
echo "    GPU_ID        = ${GPU_ID}"
echo "    OUTPUT_DIR    = ${OUTPUT_DIR}"
echo ""

DONE=0
SKIPPED=0
FAILED=0

for cfg in "${CONFIGS[@]}"; do
    stem="$(basename "${cfg}" .yaml)"
    idx=$((DONE + SKIPPED + FAILED + 1))
    echo "[${idx}/${TOTAL}] ${stem}"

    # Check manifest for skip
    if [[ "${SKIP_EXISTING}" == "1" ]] && [[ -f "${MANIFEST}" ]]; then
        if grep -q "^${stem}," "${MANIFEST}" 2>/dev/null; then
            echo "  → already in manifest, skipping"
            SKIPPED=$((SKIPPED + 1))
            continue
        fi
    fi

    if python src/hergbench/stage2_pipeline.py --config "${cfg}"; then
        DONE=$((DONE + 1))
        echo "  → done"
    else
        echo "  → FAILED (exit $?)" >&2
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "=== 04 ChEMBL Stage 2 complete ==="
echo "    done=${DONE}  skipped=${SKIPPED}  failed=${FAILED}"
if [[ "${FAILED}" -gt 0 ]]; then
    echo "  WARNING: ${FAILED} run(s) failed. Check logs above." >&2
fi
