#!/usr/bin/env bash
# =============================================================================
# runpod_multiseed_setup.sh
#
# One-shot bootstrap + multi-seed Stage 1 runner for a fresh RunPod pod.
# Trains XGBoost across all 5 seeds × 3 split types, aggregates AD-binned
# metrics, and saves everything under reports/multiseed_analysis/.
#
# Lighter than runpod_stage1_setup.sh — no exmol, no PyTDC, no counterfactuals.
# Requires the processed dataset and split CSVs to already be present in the repo
# (they should be committed / rsync-ed before launching the pod).
#
# Usage (from repo root):
#   bash scripts/runpod_multiseed_setup.sh
#
# Optional env vars:
#   VENV_DIR      — venv location             (default: /workspace/venv_hergbench)
#   OUTPUT_DIR    — results destination       (default: reports/multiseed_analysis)
#   SKIP_EXISTING — pass --no-skip-existing   (default: 1, i.e. reuse cached results)
#   SKIP_RUN      — set to 1 to install only  (default: 0)
#   RANDOM_STATE  — master XGBoost seed       (default: 42)
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# 0. Locate repo root
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo ""
echo "================================================================"
echo "  hERGBench — Multi-seed Stage 1 benchmark — RunPod bootstrap"
echo "  Repo root  : ${REPO_ROOT}"
echo "  Date/time  : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "================================================================"
echo ""

cd "${REPO_ROOT}"

# ---------------------------------------------------------------------------
# 0b. System libraries (RDKit drawing deps — same as Stage 1 script)
# ---------------------------------------------------------------------------
if command -v apt-get >/dev/null 2>&1; then
    echo "[setup] Installing required system libraries..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y >/dev/null
    apt-get install -y --no-install-recommends \
        libxrender1 \
        libxext6 \
        libsm6 \
        libx11-6 \
        libglib2.0-0 >/dev/null
else
    echo "[setup] apt-get not available; assuming system libraries are present."
fi

# ---------------------------------------------------------------------------
# 1. Python sanity check (need 3.11+)
# ---------------------------------------------------------------------------
_py_bin=""
for candidate in python3.11 python3.12 python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1; then
        major=$("${candidate}" -c 'import sys; print(sys.version_info[0])')
        minor=$("${candidate}" -c 'import sys; print(sys.version_info[1])')
        if [[ "${major}" -ge 3 && "${minor}" -ge 11 ]]; then
            _py_bin="${candidate}"
            break
        fi
    fi
done

if [[ -z "${_py_bin}" ]]; then
    echo "[ERROR] Python 3.11+ not found." >&2
    echo "        Tip: use the 'runpod/pytorch:2.3.0-py3.11-cuda12.1.1-devel-ubuntu22.04' template." >&2
    exit 1
fi

echo "[setup] Python binary : $("${_py_bin}" --version)"

# ---------------------------------------------------------------------------
# 2. Create / reuse venv
# ---------------------------------------------------------------------------
VENV_DIR="${VENV_DIR:-/workspace/venv_hergbench}"

if [[ -d "${VENV_DIR}" && -f "${VENV_DIR}/bin/activate" ]]; then
    echo "[setup] Reusing existing venv at ${VENV_DIR}"
else
    echo "[setup] Creating venv at ${VENV_DIR}"
    "${_py_bin}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
PY="${VENV_DIR}/bin/python"
PIP="${VENV_DIR}/bin/pip"

echo "[setup] Active Python : $("${PY}" --version)"
echo "[setup] pip           : $("${PIP}" --version)"

# ---------------------------------------------------------------------------
# 3. Upgrade pip / build tools
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Upgrading pip, setuptools, wheel..."
"${PIP}" install --quiet --upgrade pip setuptools wheel

# ---------------------------------------------------------------------------
# 4. Install dependencies
#
# No exmol, no PyTDC, no counterfactual stack — just the XGBoost / metrics
# dependencies needed for train → calibrate → evaluate → aggregate.
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Step 4a: core scientific stack..."
"${PIP}" install --quiet \
    "numpy>=2.0,<3" \
    "pandas>=2.0" \
    "scikit-learn>=1.3" \
    "matplotlib>=3.7" \
    "joblib>=1.3" \
    "scipy>=1.11"

echo "[setup] Step 4b: rdkit..."
"${PIP}" install --quiet "rdkit>=2023.9"

"${PY}" -c "from rdkit import Chem; assert Chem.MolFromSmiles('CCO') is not None" \
    || { echo "[ERROR] rdkit import/sanity check failed." >&2; exit 1; }
echo "[setup]   rdkit OK: $("${PY}" -c 'import rdkit; print(rdkit.__version__)')"

echo "[setup] Step 4c: XGBoost + Optuna..."
"${PIP}" install --quiet "xgboost>=2.0" "optuna>=3.6"

echo "[setup] Step 4d: typer + PyYAML (CLI)..."
"${PIP}" install --quiet "typer>=0.12" "pyyaml>=6.0"

# ---------------------------------------------------------------------------
# 5. Install hergbench (editable, no extra deps)
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Step 5: installing hergbench in editable mode..."
"${PIP}" install --quiet -e "${REPO_ROOT}" --no-deps

HERGBENCH_BIN="${VENV_DIR}/bin/hergbench"
if [[ ! -f "${HERGBENCH_BIN}" ]]; then
    echo "[ERROR] hergbench CLI not found at ${HERGBENCH_BIN} after install." >&2
    exit 1
fi
echo "[setup]   hergbench CLI : ${HERGBENCH_BIN}"

# ---------------------------------------------------------------------------
# 6. Import smoke test
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Step 6: import smoke test..."
"${PY}" - <<'PYEOF'
import sys

checks = [
    ("numpy",                     "import numpy as np; print('  numpy', np.__version__)"),
    ("pandas",                    "import pandas as pd; print('  pandas', pd.__version__)"),
    ("rdkit",                     "from rdkit import Chem, DataStructs; print('  rdkit OK')"),
    ("sklearn",                   "import sklearn; print('  sklearn', sklearn.__version__)"),
    ("xgboost",                   "import xgboost; print('  xgboost', xgboost.__version__)"),
    ("optuna",                    "import optuna; print('  optuna', optuna.__version__)"),
    ("hergbench.features",        "from hergbench.features.fingerprints import FingerprintConfig, bulk_max_tanimoto; print('  fingerprints OK')"),
    ("hergbench.evaluation",      "from hergbench.evaluation.eval import compute_metrics, calibrate_prefit; print('  eval OK')"),
    ("hergbench.models",          "from hergbench.models.xgb_optuna import tune_xgb, fit_xgb; print('  xgb_optuna OK')"),
    ("hergbench.data.splits",     "from hergbench.data.splits import split_df; print('  splits OK')"),
    ("hergbench.analysis",        "from hergbench.analysis import run_multiseed_benchmark, aggregate_multiseed_results; print('  analysis OK')"),
]

failed = []
for name, stmt in checks:
    try:
        exec(stmt)
    except Exception as e:
        print(f"  [FAIL] {name}: {e}", file=sys.stderr)
        failed.append(name)

if failed:
    print(f"\n[ERROR] {len(failed)} import(s) failed: {failed}", file=sys.stderr)
    sys.exit(1)
else:
    print("\n  All imports OK.")
PYEOF

# ---------------------------------------------------------------------------
# 7. Check required data files
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Step 7: checking required data files..."

DATASET_PATH="${REPO_ROOT}/data/processed/herg_clean.csv"
SPLITS_DIR="${REPO_ROOT}/data/splits"

_check_file() {
    if [[ -f "${REPO_ROOT}/$1" ]]; then
        echo "[setup]   found    : $1"
    else
        echo "[setup]   MISSING  : $1"
    fi
}

_check_file "data/processed/herg_clean.csv"

if [[ ! -f "${DATASET_PATH}" ]]; then
    echo "[ERROR] Processed dataset not found at ${DATASET_PATH}." >&2
    echo "        This script does not run PyTDC. Copy herg_clean.csv into data/processed/ first." >&2
    exit 1
fi

# Verify all 15 split CSVs are present
EXPECTED_SPLITS=15
FOUND_SPLITS=0
MISSING_SPLITS=()

for split_type in random scaffold cluster; do
    for seed in 11 22 33 44 55; do
        f="${SPLITS_DIR}/${split_type}_seed${seed}.csv"
        if [[ -f "${f}" ]]; then
            FOUND_SPLITS=$(( FOUND_SPLITS + 1 ))
        else
            MISSING_SPLITS+=("${split_type}_seed${seed}.csv")
        fi
    done
done

echo "[setup]   splits found: ${FOUND_SPLITS} / ${EXPECTED_SPLITS}"

if [[ ${#MISSING_SPLITS[@]} -gt 0 ]]; then
    echo "[ERROR] Missing split files:" >&2
    for f in "${MISSING_SPLITS[@]}"; do
        echo "          data/splits/${f}" >&2
    done
    echo "        Run 'hergbench stage1 -c configs/stage1_signoff.yaml' locally first to generate splits," >&2
    echo "        then commit data/splits/ to the repo before launching this pod." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 8. Environment summary
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Environment summary:"
echo "  Python  : $("${PY}" --version)"
echo "  rdkit   : $("${PY}" -c 'import rdkit; print(rdkit.__version__)')"
echo "  xgboost : $("${PY}" -c 'import xgboost; print(xgboost.__version__)')"
echo "  optuna  : $("${PY}" -c 'import optuna; print(optuna.__version__)')"
echo "  Dataset : ${DATASET_PATH} ($("${PY}" -c "import pandas as pd; print(len(pd.read_csv('${DATASET_PATH}')), 'rows')"))"
echo "  Splits  : ${FOUND_SPLITS} / ${EXPECTED_SPLITS} present"

# ---------------------------------------------------------------------------
# 9. Run multi-seed benchmark
# ---------------------------------------------------------------------------
OUTPUT_DIR="${OUTPUT_DIR:-reports/multiseed_analysis}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
SKIP_RUN="${SKIP_RUN:-0}"
RANDOM_STATE="${RANDOM_STATE:-42}"

if [[ "${SKIP_RUN}" == "1" ]]; then
    echo ""
    echo "[setup] SKIP_RUN=1 — skipping benchmark execution."
    echo "[setup] To run manually:"
    echo "  source ${VENV_DIR}/bin/activate"
    echo "  cd ${REPO_ROOT}"
    echo "  python scripts/run_multiseed_stage1.py --output-dir ${OUTPUT_DIR}"
    exit 0
fi

# Build the runner args
RUNNER_ARGS=("--output-dir" "${OUTPUT_DIR}" "--random-state" "${RANDOM_STATE}")
if [[ "${SKIP_EXISTING}" == "0" ]]; then
    RUNNER_ARGS+=("--no-skip-existing")
fi

echo ""
echo "================================================================"
echo "  Starting multi-seed benchmark"
echo "  Seeds      : 11 22 33 44 55"
echo "  Split types: random scaffold cluster"
echo "  Output     : ${REPO_ROOT}/${OUTPUT_DIR}"
echo "  Skip cache : ${SKIP_EXISTING}"
echo "================================================================"
echo ""

cd "${REPO_ROOT}"
"${PY}" scripts/run_multiseed_stage1.py "${RUNNER_ARGS[@]}"

echo ""
echo "================================================================"
echo "  Multi-seed benchmark complete."
echo "  Artifacts:"
echo "    ${OUTPUT_DIR}/multiseed_ad_bins_raw.csv"
echo "    ${OUTPUT_DIR}/multiseed_ad_bins_aggregated.csv"
echo "    ${OUTPUT_DIR}/multiseed_benchmark_summary.csv"
echo "================================================================"
