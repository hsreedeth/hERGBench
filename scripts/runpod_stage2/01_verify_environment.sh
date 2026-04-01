#!/usr/bin/env bash
# 01_verify_environment.sh — Check GPU, CUDA, ChemProp, and dataset presence.
#
# Run from repo root:
#   bash scripts/runpod_stage2/01_verify_environment.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"
REPO_ROOT="$(stage2_repo_root)"
cd "${REPO_ROOT}"

echo "=== 01 Verify Stage 2 Environment ==="
echo "  hostname:  $(hostname)"
echo "  repo root: ${REPO_ROOT}"

activate_stage2_venv "${REPO_ROOT}" || true

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

# NumPy ABI sanity check before touching RDKit/ChemProp wheels.
python - <<'PY'
import sys

try:
    import numpy as np
except Exception as exc:  # pragma: no cover - shell preflight path
    print(f"ERROR: numpy import failed: {exc}", file=sys.stderr)
    raise SystemExit(1)

print(f"  numpy:     {np.__version__}")

major = int(np.__version__.split(".", 1)[0])
if major >= 2:
    print(
        "ERROR: NumPy 2.x detected. Current rdkit/chemprop wheels on RunPod require NumPy < 2.\n"
        "Run: bash scripts/runpod_4090/02_setup_repo_env.sh",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY

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
