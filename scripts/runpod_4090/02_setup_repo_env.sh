#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

echo "[02_setup_repo_env] upgrading pip/setuptools/wheel"
python -m pip install --upgrade pip setuptools wheel

echo "[02_setup_repo_env] installing Stage 2 runtime deps with NumPy < 2"
python -m pip install \
  "numpy<2" \
  "pandas>=2,<3" \
  "scikit-learn>=1.3" \
  "matplotlib>=3.7" \
  "pyyaml>=6.0" \
  "typer>=0.12" \
  "joblib>=1.3"

if ! python -c "import torch" >/dev/null 2>&1; then
  echo "[02_setup_repo_env] installing CUDA PyTorch"
  python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
fi

echo "[02_setup_repo_env] installing repo in editable mode without deps"
echo "[02_setup_repo_env] note: pyproject currently declares numpy>=2, which is incompatible with current rdkit/chemprop wheels on RunPod"
python -m pip install -e . --no-deps

if ! python -c "import chemprop" >/dev/null 2>&1; then
  echo "[02_setup_repo_env] installing chemprop"
  python -m pip install chemprop
fi

if ! python -c "from rdkit import Chem" >/dev/null 2>&1; then
  echo "[02_setup_repo_env] installing rdkit"
  python -m pip install rdkit
fi

echo "[02_setup_repo_env] enforcing NumPy < 2 after wheel installs"
python -m pip install --force-reinstall "numpy<2"

mkdir -p reports/runs reports/summary

echo "[02_setup_repo_env] environment summary"
echo "python: $(python --version 2>&1)"
echo "pip: $(python -m pip --version)"
echo "torch: $(python -c 'import torch; print(torch.__version__)' 2>/dev/null || echo missing)"
echo "numpy: $(python -c 'import numpy; print(numpy.__version__)' 2>/dev/null || echo missing)"
echo "chemprop: $(command -v chemprop || echo missing)"
python -m pip show hergbench-tdc | sed -n '1,8p' || true
python -m pip show chemprop | sed -n '1,8p' || true
python -m pip show rdkit | sed -n '1,8p' || true
