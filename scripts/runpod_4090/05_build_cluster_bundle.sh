#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MANIFEST="reports/summary/runpod_4090_cluster_none_multitorch_runs.csv"
BUNDLE_DIR="hERGBench_Stage2_Cluster_None_MultiTorch_v1"

cd "${REPO_ROOT}"

echo "[05_build_cluster_bundle] building bundle from ${MANIFEST}"
python scripts/runpod_4090/build_cluster_none_bundle.py --manifest "${MANIFEST}" --bundle-dir "${BUNDLE_DIR}"

if [[ ! -d "${BUNDLE_DIR}" ]]; then
  echo "[05_build_cluster_bundle] bundle directory missing: ${BUNDLE_DIR}" >&2
  exit 1
fi

echo "[05_build_cluster_bundle] final bundle: ${BUNDLE_DIR}"
