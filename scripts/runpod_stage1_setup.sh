#!/usr/bin/env bash
# =============================================================================
# runpod_stage1_setup.sh
#
# One-shot bootstrap + Stage 1 runner for a fresh RunPod pod.
# Handles Python env creation, dependency install order, conflict avoidance,
# and finally runs:  hergbench stage1 -c configs/stage1_signoff.yaml
#
# Usage (from repo root):
#   bash scripts/runpod_stage1_setup.sh
#
# Optional env vars you can set before calling:
#   REPO_URL   — git remote to clone from (only used if not already in repo)
#   SKIP_RUN   — set to 1 to install only, don't run stage1
#   VENV_DIR   — override venv location (default: /workspace/venv_hergbench)
#   STAGE1_CFG — override config path (default: configs/stage1_signoff.yaml)
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# 0. Locate repo root
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo ""
echo "================================================================"
echo "  hERGBench Stage 1 — RunPod bootstrap"
echo "  Repo root : ${REPO_ROOT}"
echo "  Date/time : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "================================================================"
echo ""

cd "${REPO_ROOT}"

# ---------------------------------------------------------------------------
# 0b. System libraries needed by RDKit drawing / exmol / synspace
# ---------------------------------------------------------------------------
if command -v apt-get >/dev/null 2>&1; then
    echo "[setup] Installing required system libraries for RDKit drawing..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y >/dev/null
    apt-get install -y --no-install-recommends \
        libxrender1 \
        libxext6 \
        libsm6 \
        libx11-6 \
        libglib2.0-0 >/dev/null
else
    echo "[setup] apt-get not available; assuming required system libraries are already present."
fi

# ---------------------------------------------------------------------------
# 1. Python sanity check (need 3.11+)
# ---------------------------------------------------------------------------
_py_bin=""

for candidate in python3.11 python3.12 python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1; then
        ver="$("${candidate}" -c 'import sys; print(sys.version_info[:2])')"
        major=$("${candidate}" -c 'import sys; print(sys.version_info[0])')
        minor=$("${candidate}" -c 'import sys; print(sys.version_info[1])')
        if [[ "${major}" -ge 3 && "${minor}" -ge 11 ]]; then
            _py_bin="${candidate}"
            break
        fi
    fi
done

if [[ -z "${_py_bin}" ]]; then
    echo "[ERROR] Python 3.11+ not found. Install it or use a RunPod image that includes it." >&2
    echo "        Tip: RunPod PyTorch 2.x images ship Python 3.10. Use the 'runpod/pytorch:2.3.0-py3.11-cuda12.1.1-devel-ubuntu22.04' template." >&2
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

# Activate
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

CACHED_DATASET="${REPO_ROOT}/data/processed/herg_clean.csv"
USE_CACHED_DATASET=0
if [[ -f "${CACHED_DATASET}" ]]; then
    USE_CACHED_DATASET=1
    echo "[setup] Cached Stage 1 dataset detected at ${CACHED_DATASET}"
else
    echo "[setup] No cached processed dataset found; PyTDC will be needed to fetch hERG."
fi

# ---------------------------------------------------------------------------
# 4. Install dependencies — ORDER MATTERS
#
# Problem: PyTDC==0.4.1 pins rdkit-pypi (the old Conda-free wheel name).
#          Modern rdkit supersedes rdkit-pypi; having both installed causes
#          ImportError collisions. We install rdkit first, then tell pip to
#          treat rdkit-pypi as already satisfied via a no-op stub approach
#          (--no-deps on PyTDC + manual deps).
#
#          exmol pulls openai + synspace + skunk which are fine, but selfies
#          must be >=2.1 to match rdkit canonical SMILES behavior we rely on.
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Step 4a: core scientific stack..."
"${PIP}" install --quiet \
    "numpy>=2.0,<3" \
    "pandas>=2.0" \
    "scikit-learn>=1.3" \
    "matplotlib>=3.7" \
    "plotly>=5.20" \
    "joblib>=1.3"

echo "[setup] Step 4b: rdkit (cheminformatics — must be installed before PyTDC)..."
# Install modern rdkit. This provides the 'rdkit' package name.
"${PIP}" install --quiet "rdkit>=2023.9"

# Verify rdkit works before continuing — fail early if broken.
"${PY}" -c "from rdkit import Chem; assert Chem.MolFromSmiles('CCO') is not None" \
    || { echo "[ERROR] rdkit import/sanity check failed." >&2; exit 1; }
echo "[setup]   rdkit OK: $("${PY}" -c 'import rdkit; print(rdkit.__version__)')"

echo "[setup] Step 4c: XGBoost, Optuna..."
"${PIP}" install --quiet "xgboost>=2.0" "optuna>=3.6"

if [[ "${USE_CACHED_DATASET}" == "1" ]]; then
    echo "[setup] Step 4d: skipping PyTDC install because cached processed dataset is present."
else
    echo "[setup] Step 4d: PyTDC==0.4.1 (installed with --no-deps to avoid rdkit-pypi conflict)..."
    # PyTDC's declared dep on rdkit-pypi is stale. We install it without deps
    # and then manually add the packages it actually needs at runtime.
    "${PIP}" install --quiet --no-deps "PyTDC==0.4.1"

    # PyTDC runtime deps (excluding rdkit which is already installed).
    # Pin setuptools below 81 so pkg_resources remains available for PyTDC.
    "${PIP}" install --quiet \
        "setuptools<81" \
        "dataclasses" \
        "requests" \
        "tqdm" \
        "fuzzywuzzy" \
        "python-Levenshtein" \
        "huggingface_hub" \
        "seaborn" \
        "pyarrow"

    # Verify PyTDC can at least be imported.
    "${PY}" -c "import pkg_resources; import tdc" \
        || { echo "[ERROR] PyTDC import failed." >&2; exit 1; }
    echo "[setup]   PyTDC OK"
fi

echo "[setup] Step 4e: typer (CLI framework)..."
"${PIP}" install --quiet "typer>=0.12" "pyyaml>=6.0"

echo "[setup] Step 4f: exmol + selfies (counterfactual generation)..."
# selfies must be >=2.1; exmol will pull the rest (synspace, skunk, openai, etc.)
"${PIP}" install --quiet "selfies>=2.1"
"${PIP}" install --quiet "exmol>=3.3.0"

# Verify exmol import works.
"${PY}" -c "import exmol" \
    || { echo "[ERROR] exmol import failed." >&2; exit 1; }
echo "[setup]   exmol OK"

# ---------------------------------------------------------------------------
# 5. Install hergbench itself (editable)
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Step 5: installing hergbench in editable mode..."
"${PIP}" install --quiet -e "${REPO_ROOT}" --no-deps

# Verify the CLI entry point exists.
HERGBENCH_BIN="${VENV_DIR}/bin/hergbench"
if [[ ! -f "${HERGBENCH_BIN}" ]]; then
    echo "[ERROR] hergbench CLI not found at ${HERGBENCH_BIN} after install." >&2
    exit 1
fi
echo "[setup]   hergbench CLI : ${HERGBENCH_BIN}"

# ---------------------------------------------------------------------------
# 6. Full import smoke test — catch any missing dep before the real run
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Step 6: import smoke test..."
"${PY}" - <<PYEOF
import sys

use_cached_dataset = ${USE_CACHED_DATASET}

checks = [
    ("numpy",             "import numpy as np; print('  numpy', np.__version__)"),
    ("pandas",            "import pandas as pd; print('  pandas', pd.__version__)"),
    ("rdkit",             "from rdkit import Chem; from rdkit.Chem.Scaffolds import MurckoScaffold; print('  rdkit OK')"),
    ("sklearn",           "import sklearn; print('  sklearn', sklearn.__version__)"),
    ("xgboost",           "import xgboost; print('  xgboost', xgboost.__version__)"),
    ("optuna",            "import optuna; print('  optuna', optuna.__version__)"),
    ("exmol",             "import exmol; print('  exmol OK')"),
    ("hergbench.cli",     "from hergbench.cli import app; print('  hergbench.cli OK')"),
    ("hergbench.stage1",  "from hergbench.stage1_pipeline import run_stage1; print('  hergbench.stage1_pipeline OK')"),
    ("hergbench.lead_opt","from hergbench.reporting.lead_opt import generate_counterfactuals_exmol, _generic_scaffold_smi; print('  lead_opt OK (scaffold fn present)')"),
]

if not use_cached_dataset:
    checks.append(("tdc", "import pkg_resources; import tdc; print('  PyTDC OK')"))

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
# 7. Check data files are in place
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Step 7: checking required data files..."

_check_file() {
    if [[ -f "${REPO_ROOT}/$1" ]]; then
        echo "[setup]   found: $1"
    else
        echo "[setup]   missing: $1"
    fi
}

_check_file "data/processed/herg_clean.csv"
_check_file "configs/stage1_signoff.yaml"
_check_file "configs/panels/stage1_signoff_panel_seed42_n30.csv"

if [[ "${USE_CACHED_DATASET}" == "0" ]]; then
    echo "[setup]   processed dataset absent; Stage 1 will need PyTDC fetch on first run."
fi

# Splits are generated on first run; just warn if absent.
if ls "${REPO_ROOT}/data/splits/"*.csv >/dev/null 2>&1; then
    echo "[setup]   splits present ($(ls "${REPO_ROOT}/data/splits/"*.csv | wc -l | tr -d ' ') files)"
else
    echo "[setup]   splits absent — will be generated on first run (expected)"
fi

# ---------------------------------------------------------------------------
# 8. Print environment summary to stdout (captured in run log)
# ---------------------------------------------------------------------------
echo ""
echo "[setup] Environment summary:"
echo "  Python  : $("${PY}" --version)"
echo "  rdkit   : $("${PY}" -c 'import rdkit; print(rdkit.__version__)')"
echo "  exmol   : $("${PY}" -c 'import exmol; print(getattr(exmol, "__version__", "?"))')"
echo "  xgboost : $("${PY}" -c 'import xgboost; print(xgboost.__version__)')"
echo "  optuna  : $("${PY}" -c 'import optuna; print(optuna.__version__)')"

# ---------------------------------------------------------------------------
# 9. Run Stage 1
# ---------------------------------------------------------------------------
STAGE1_CFG="${STAGE1_CFG:-configs/stage1_signoff.yaml}"
SKIP_RUN="${SKIP_RUN:-0}"

if [[ "${SKIP_RUN}" == "1" ]]; then
    echo ""
    echo "[setup] SKIP_RUN=1 — skipping stage1 execution."
    echo "[setup] To run manually:"
    echo "  source ${VENV_DIR}/bin/activate"
    echo "  cd ${REPO_ROOT}"
    echo "  hergbench stage1 -c ${STAGE1_CFG}"
    exit 0
fi

echo ""
echo "================================================================"
echo "  Starting Stage 1"
echo "  Config : ${STAGE1_CFG}"
echo "  Output : ${REPO_ROOT}/reports/runs/"
echo "================================================================"
echo ""

cd "${REPO_ROOT}"
"${HERGBENCH_BIN}" stage1 -c "${STAGE1_CFG}"

echo ""
echo "================================================================"
echo "  Stage 1 complete."
echo "  Artifacts: ${REPO_ROOT}/reports/runs/"
echo "================================================================"
