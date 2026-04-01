#!/usr/bin/env bash
# 01_verify_data.sh — Confirm ChEMBL dataset and splits are present before training.
#
# Run from repo root on the pod:
#   bash scripts/runpod_chembl/01_verify_data.sh

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(pwd)}"
SEEDS=(11 22 33 44 55)
SPLIT_TYPES=(random scaffold cluster)
DATA_CSV="${REPO_DIR}/data/chembl/processed/chembl_herg_clean.csv"
SPLITS_DIR="${REPO_DIR}/data/chembl/splits"

echo "=== 01 Verify ChEMBL data ==="

# Dataset CSV
if [[ ! -f "${DATA_CSV}" ]]; then
    echo "ERROR: dataset not found: ${DATA_CSV}"
    echo "Run: hergbench curate-chembl --output-dir data/chembl"
    exit 1
fi
N_ROWS=$(tail -n +2 "${DATA_CSV}" | wc -l | tr -d ' ')
echo "  Dataset: ${DATA_CSV}  (${N_ROWS} rows)"

# Split CSVs — all 15 required
MISSING=0
for st in "${SPLIT_TYPES[@]}"; do
    for seed in "${SEEDS[@]}"; do
        CSV="${SPLITS_DIR}/${st}_seed${seed}.csv"
        if [[ ! -f "${CSV}" ]]; then
            echo "  MISSING: ${CSV}"
            MISSING=$((MISSING + 1))
        fi
    done
done

if [[ "${MISSING}" -gt 0 ]]; then
    echo "ERROR: ${MISSING} split file(s) missing under ${SPLITS_DIR}."
    echo "Re-run curate-chembl or sync splits from local machine."
    exit 1
fi

echo "  Splits:  all 15 files present in ${SPLITS_DIR}"
echo "=== Verification passed — ready to train ==="
