#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONFIG="configs/runpod_4090/stage2_chemprop_cluster_seed11_none_cuda_torch42.yaml"

cd "${REPO_ROOT}"

export HERGBENCH_ALLOW_GPU=1

echo "[03_smoke_test_cluster_none] running ${CONFIG}"
python src/hergbench/stage2_pipeline.py --config "${CONFIG}"

RUN_DIR="$(ls -td reports/runs/*stage2_chemprop_cluster_seed11_torch42 | head -n 1)"
if [[ ! -d "${RUN_DIR}" ]]; then
  echo "[03_smoke_test_cluster_none] failed to locate smoke-test run directory." >&2
  exit 1
fi

if [[ ! -f "${RUN_DIR}/tables/benchmark_results.csv" ]]; then
  echo "[03_smoke_test_cluster_none] benchmark_results.csv missing in ${RUN_DIR}" >&2
  exit 1
fi

echo "[03_smoke_test_cluster_none] artifacts: ${RUN_DIR}"
