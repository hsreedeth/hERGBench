#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

echo "[01_system_check] hostname: $(hostname)"
python --version

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "[01_system_check] nvidia-smi was not found. Use a CUDA-enabled Runpod image." >&2
  exit 1
fi

echo "[01_system_check] nvidia-smi"
nvidia-smi

echo "[01_system_check] torch CUDA check"
python scripts/runpod_4090/check_torch_cuda.py
