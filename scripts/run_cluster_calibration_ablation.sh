#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

python src/hergbench/stage2_pipeline.py --config configs/stage2_chemprop_cluster_seed11_platt.yaml
python src/hergbench/stage2_pipeline.py --config configs/stage2_chemprop_cluster_seed11_none.yaml
python src/hergbench/stage2_pipeline.py --config configs/stage2_chemprop_cluster_seed11_isotonic.yaml
