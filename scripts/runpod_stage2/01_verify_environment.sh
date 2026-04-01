#!/usr/bin/env bash
# 01_verify_environment.sh — Check GPU, CUDA, ChemProp, and dataset presence.
#
# Run from repo root:
#   bash scripts/runpod_stage2/01_verify_environment.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

VENV_DIR="${VENV_DIR:-/workspace/hERGBench/.venv}"

echo "=== 01 Verify Stage 2 Environment ==="
echo "  hostname:  $(hostname)"
echo "  repo root: ${REPO_ROOT}"

# Activate venv if present
if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
    echo "  venv:      ${VENV_DIR}"
else
    echo "  WARNING: venv not found at ${VENV_DIR} — using system Python"
fi

python --version

# GPU check
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "ERROR: nvidia-smi not found. Use a CUDA-enabled RunPod image." >&2
    exit 1
fi
echo ""
nvidia-smi
echo ""

# PyTorch + CUDA
python scripts/runpod_4090/check_torch_cuda.py

# ChemProp
if ! python -c "import chemprop" >/dev/null 2>&1; then
    echo "ERROR: chemprop not importable. Run 02_setup (from runpod_4090) first." >&2
    exit 1
fi
echo "  chemprop:  $(python -c 'import chemprop; print(chemprop.__version__)')"

# Datasets
ERRORS=0
for f in \
    "data/processed/herg_clean.csv" \
    "data/chembl/processed/chembl_herg_clean.csv"; do
    if [[ ! -f "${f}" ]]; then
        echo "  MISSING dataset: ${f}"
        ERRORS=$((ERRORS + 1))
    else
        N=$(tail -n +2 "${f}" | wc -l | tr -d ' ')
        echo "  dataset OK: ${f}  (${N} rows)"
    fi
done

# Split dirs
for dir_path in "data/splits" "data/chembl/splits"; do
    count=$(ls "${dir_path}"/*.csv 2>/dev/null | wc -l | tr -d ' ')
    if [[ "${count}" -lt 15 ]]; then
        echo "  WARNING: only ${count}/15 split CSVs in ${dir_path}"
        ERRORS=$((ERRORS + 1))
    else
        echo "  splits OK: ${dir_path}  (${count} files)"
    fi
done

if [[ "${ERRORS}" -gt 0 ]]; then
    echo "ERROR: ${ERRORS} issue(s) found. Fix before continuing." >&2
    exit 1
fi

echo ""
echo "=== 01 Environment OK — ready for Stage 2 ==="
