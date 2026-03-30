#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

echo "[02_setup_repo_env] upgrading pip/setuptools/wheel"
python -m pip install --upgrade pip setuptools wheel

echo "[02_setup_repo_env] installing repo in editable mode"
python -m pip install -e .

if ! python -c "import chemprop" >/dev/null 2>&1; then
  echo "[02_setup_repo_env] installing chemprop"
  python -m pip install chemprop
fi

if ! python -c "from rdkit import Chem" >/dev/null 2>&1; then
  echo "[02_setup_repo_env] installing rdkit"
  python -m pip install rdkit
fi

mkdir -p reports/runs reports/summary

echo "[02_setup_repo_env] environment summary"
echo "python: $(python --version 2>&1)"
echo "pip: $(python -m pip --version)"
echo "chemprop: $(command -v chemprop || echo missing)"
python -m pip show hergbench-tdc | sed -n '1,8p' || true
python -m pip show chemprop | sed -n '1,8p' || true
python -m pip show rdkit | sed -n '1,8p' || true
