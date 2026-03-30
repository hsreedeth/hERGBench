#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONFIG_DIR="configs/runpod_4090/stage2_multitorch"
MANIFEST="reports/summary/runpod_4090_cluster_none_multitorch_runs.csv"

cd "${REPO_ROOT}"

export HERGBENCH_ALLOW_GPU=1

mkdir -p "$(dirname "${MANIFEST}")"
printf "config_path,pytorch_seed,run_dir\n" > "${MANIFEST}"

CONFIGS=(
  "${CONFIG_DIR}/stage2_chemprop_cluster_seed11_none_cuda_torch11.yaml"
  "${CONFIG_DIR}/stage2_chemprop_cluster_seed11_none_cuda_torch22.yaml"
  "${CONFIG_DIR}/stage2_chemprop_cluster_seed11_none_cuda_torch33.yaml"
  "${CONFIG_DIR}/stage2_chemprop_cluster_seed11_none_cuda_torch44.yaml"
  "${CONFIG_DIR}/stage2_chemprop_cluster_seed11_none_cuda_torch55.yaml"
)

for cfg in "${CONFIGS[@]}"; do
  seed="$(basename "${cfg}" | sed -E 's/.*torch([0-9]+)\.yaml/\1/')"
  echo "[04_run_cluster_none_multitorch] seed=${seed} config=${cfg}"
  python src/hergbench/stage2_pipeline.py --config "${cfg}"

  run_dir="$(ls -td reports/runs/*stage2_chemprop_cluster_seed11_torch${seed} | head -n 1)"
  if [[ ! -f "${run_dir}/tables/benchmark_results.csv" ]]; then
    echo "[04_run_cluster_none_multitorch] expected benchmark_results.csv missing for ${run_dir}" >&2
    exit 1
  fi

  printf "%s,%s,%s\n" "${cfg}" "${seed}" "${run_dir}" >> "${MANIFEST}"
done

echo "[04_run_cluster_none_multitorch] manifest: ${MANIFEST}"
